import argparse
import json
import logging
import os
import re
import sys
import xml.dom.minidom
from collections import OrderedDict

import anymarkup
import urllib3
import yaml
from pyzabbix import ZabbixAPI

urllib3.disable_warnings()


def remove_none(obj):
    """
    Remove None value from any object
    As is from https://stackoverflow.com/a/20558778/6753144
    :param obj:
    :return:
    """
    if isinstance(obj, (list, tuple, set)):
        return type(obj)(remove_none(x) for x in obj if x is not None)
    elif isinstance(obj, dict):
        return type(obj)((remove_none(k), remove_none(v))
                         for k, v in obj.items() if k is not None and v is not None)
    else:
        return obj


def get_zabbix_connection(zbx_url, zbx_user, zbx_password):
    """
    Иногда на сервере или у разработчика могут быть разные версии библиотек-pip-модули: pyzabbix\py-zabbix
    Но обе они имеют имя python-модуля pyzabbix, но немного различные интерфейсы
    Функция автоматически определяет какая библиотека установлена
        (точнее, пробует обе) и возвращает готовый объект ZabbixAPI
    :param zbx_user:
    :param zbx_password:
    :param zbx_url:
    :return:
    """
    # pyzabbix library, with user\password in login method. It's GOOD library
    logging.debug("Try connect to Zabbix by pyzabbix...")
    try:
        zbx_pyzabbix = ZabbixAPI(zbx_url)
        zbx_pyzabbix.session.verify = False
        zbx_pyzabbix.login(zbx_user, zbx_password)
        return zbx_pyzabbix
    except Exception as e:
        logging.exception(e)

    # py-zabbix library, with user\password in ZabbixAPI
    logging.debug("Try connect to Zabbix by py-zabbix...")
    try:
        zbx_py_zabbix = ZabbixAPI(zbx_url, user=zbx_user, password=zbx_password)
        zbx_py_zabbix.session.verify = False
        return zbx_py_zabbix
    except Exception as e:
        logging.exception(e)
    # choose good API

    raise Exception("Some error in pyzabbix or py_zabbix module, see logs")


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--zabbix-url", action="store", required=True)
    parser.add_argument("--zabbix-username", action="store", required=True)
    parser.add_argument("--zabbix-password", action="store", required=True)

    parser.add_argument("--save-yaml", action="store_true")

    args = parser.parse_args()
    return args


def init_logging(level=logging.INFO):
    logger_format_string = '%(levelname)-8s %(message)s'
    logging.basicConfig(level=level, format=logger_format_string, stream=sys.stdout)


def order_data(data):
    if isinstance(data, dict):
        for key, value in data.items():
            data[key] = order_data(value)
        return OrderedDict(sorted(data.items()))
    elif isinstance(data, list):
        return [order_data(x) for x in data]
    else:
        return data


def dumps_json(folder, data, key='name', save_yaml=False):
    """
    Создаёт JSON-файл в папке folder с содержимым из data (должен быть массивом!),
    key имя свойства в элементе для создания файла
    :param folder: Папка для сохранения
    :param data: List
    :param key:
    :param save_yaml:
    :return: None
    """
    if not os.path.exists(folder):
        os.makedirs(folder)

    data = order_data(data)

    for item in data:
        txt = json.dumps(item, indent=4)

        # Убираем из имени лишние символы
        name = item[key]
        name = re.sub(r'[\\/:"*?<>|]+', ' ', name)
        filename = '{}/{}.{}'.format(folder, name, 'yaml' if save_yaml else 'json')
        filename = os.path.abspath(filename)

        logging.debug("Write to file '{}'".format(filename))

        if save_yaml:
            txt = convert_to_object_without_none(txt)

        with open(filename, mode="w", encoding='utf-8', newline='\n') as file:
            file.write(txt)


def convert_to_object_without_none(txt):
    raw = anymarkup.parse(txt)
    raw = remove_none(raw)
    represent_dict_order = lambda self, data: self.represent_mapping('tag:yaml.org,2002:map', data.items())  # noqa
    yaml.add_representer(OrderedDict, represent_dict_order)
    txt = yaml.dump(raw, default_flow_style=False, width=10000)
    return txt


def dump_xml(folder, txt, name, save_yaml=False):
    """
    Создаёт XML-файл в папке folder с содержимым из text, файл name
    key имя свойства в элементе для создания файла
    :param folder: Папка для сохранения
    :param txt:
    :param name:
    :param save_yaml:
    :return: None
    """
    if not os.path.exists(folder):
        os.makedirs(folder)

    # Убираем из имени лишние символы
    name = re.sub(r'[\\/:"*?<>|]+', ' ', name)
    filename = '{}/{}.{}'.format(folder, name, 'yaml' if save_yaml else 'xml')
    filename = os.path.abspath(filename)

    # Убираем из xml лишние строки
    # date
    # zabbix.version
    txt = re.sub(r'<date>.*<\/date>', '', txt)
    # txt = re.sub(r'<version>.*<\/version>', '', txt)

    # ppretty xml
    xml_ = xml.dom.minidom.parseString(txt)  # or xml.dom.minidom.parseString(xml_string)
    txt = xml_.toprettyxml(indent='  ', encoding='UTF-8')
    txt = txt.decode()

    # replace xml quot to normal readable "
    txt = txt.replace('&quot;', '"')

    if save_yaml:
        txt = convert_to_object_without_none(txt)

    logging.debug("Write to file '{}'".format(filename))
    with open(filename, mode="w", encoding='utf-8', newline='\n') as file:
        file.write(txt)


def main(zabbix_, save_yaml):
    # XML
    # Standart zabbix xml export via API
    def export(zabbix_api, type, itemid, name):
        """
        Export one type: hosts, template, screen or other
        https://www.zabbix.com/documentation/4.0/manual/api/reference/configuration/export
        :param zabbix_api:
        :param type:
        :param itemid:
        :param name:
        :return:
        """
        logging.info("Export {}".format(type))
        items = zabbix_api.get()
        for item in items:
            logging.info("Processing {}...".format(item[name]))
            txt = zabbix_.configuration.export(format='xml', options={type: [item[itemid]]})
            dump_xml(folder=type, txt=txt, name=item[name], save_yaml=save_yaml)
    if yaml:
        logging.info("Convert all format to yaml")

    logging.info("Start export XML part...")
    export(zabbix_.host, 'hosts', 'hostid', 'name')
    export(zabbix_.template, 'templates', 'templateid', 'name')
    export(zabbix_.valuemap, 'valueMaps', 'valuemapid', 'name')
    export(zabbix_.screen, 'screens', 'screenid', 'name')

    # JSON
    # not support `export` method
    # Read more in https://www.zabbix.com/documentation/4.0/manual/api/reference/configuration/export

    logging.info("Start export JSON part...")
    logging.info("Processing action...")
    actions = zabbix_.action.get(selectOperations='extend', selectFilter='extend')
    dumps_json(folder='actions', data=actions, save_yaml=save_yaml)

    logging.info("Processing mediatypes...")
    mediatypes = zabbix_.mediatype.get(selectUsers='extend')
    dumps_json(folder='mediatypes', data=mediatypes, key='description', save_yaml=save_yaml)


if __name__ == "__main__":
    args = parse_args()
    init_logging()

    zabbix_ = get_zabbix_connection(args.zabbix_url, args.zabbix_username, args.zabbix_password)

    main(zabbix_=zabbix_, save_yaml=args.save_yaml)

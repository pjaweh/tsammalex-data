import os
import sys
import json
import csv
import shutil
import re
from xml.etree import cElementTree as et

import requests
from purl import URL

import tsammalexdata


PY3 = sys.version_info[0] == 3
ID_SEP_PATTERN = re.compile('\.|,|;')


def unique(iterable):
    return list(sorted(set(i for i in iterable if i)))


def split_ids(s):
    return unique(id_.strip() for id_ in ID_SEP_PATTERN.split(s) if id_.strip())


def data_file(*comps):
    return os.path.join(os.path.dirname(tsammalexdata.__file__), 'data', *comps)


def csv_items(name, lineno=False):
    data = data_file(name)
    if os.path.isdir(data):
        fnames = [os.path.join(data, fname) for fname in os.listdir(data) if fname.endswith('.csv')]
    elif os.path.isfile(data):
        fnames = [data]
    elif os.path.isfile(data + '.csv'):
        fnames = [data + '.csv']
    else:
        raise ValueError(name)

    items = []
    for fname in fnames:
        with open(data_file(fname)) as csvfile:
            for item in csv.DictReader(csvfile):
                items.append(item)
    return items


def visit(name, visitor=None):
    """Utility function to rewrite rows in csv files.

    :param name: Name of the csv file to operate on.
    :param visitor: A callable that takes a row as input and returns a (modified) row or\
    None to filter out the row.
    """
    if visitor is None:
        visitor = lambda r: r
    fname = data_file(name)
    tmp = os.path.join(os.path.dirname(fname), '.' + os.path.basename(fname))
    with open(fname, 'rb') as source:
        with open(tmp, 'wb') as target:
            writer = csv.writer(target)
            for i, row in enumerate(csv.reader(source)):
                row = visitor(i, row)
                if row:
                    writer.writerow(row)
    shutil.move(tmp, fname)


def jsondump(obj, path, **kw):
    """python 2 + 3 compatible version of json.dump.

    :param obj: The object to be dumped.
    :param path: The path of the JSON file to be written.
    """
    _kw = dict(mode='w')
    if PY3:  # pragma: no cover
        _kw['encoding'] = 'utf8'
    with open(path, **_kw) as fp:
        return json.dump(obj, fp, **kw)


def jsonload(path, default=None, **kw):
    """python 2 + 3 compatible version of json.load.

    :return: The python object read from path.
    """
    if not os.path.exists(path) and default is not None:
        return default
    _kw = {}
    if PY3:  # pragma: no cover
        _kw['encoding'] = 'utf8'
    with open(path, **_kw) as fp:
        return json.load(fp, **kw)


class DataProvider(object):
    host = 'example.org'
    scheme = 'http'

    def __enter__(self):
        if not os.path.isdir(data_file('external', self.name)):
            self._fname = data_file('external', self.name + '.json')
            self._data = jsonload(self._fname, default={})
        else:
            self._fname, self._data = None, None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._data and self._fname:
            jsondump(self._data, self._fname)

    @property
    def name(self):
        return self.__class__.__name__.lower()

    def url(self, path):
        base = URL(scheme=self.scheme, host=self.host)
        return base.path(path)

    def get(self, path, type='json', **params):
        res = requests.get(self.url(path), params=params)
        if type == 'json':
            return res.json()
        if type == 'xml':
            return et.fromstring(res.content)
        return res

    def get_id(self, name):
        raise NotImplementedError()

    def get_info(self, id):
        raise NotImplementedError()

    def cli(self, arg):
        try:
            int(arg)
            return self.get_info(arg)
        except ValueError:
            return self.get_id(arg)

    def get_cached(self, sid, id):
        if os.path.isdir(data_file('external', self.name)):
            fname = data_file('external', self.name, sid + '.json')
            if not os.path.exists(fname):
                try:
                    data = self.get_info(id)
                except:
                    data = None
                if not data:
                    return
                jsondump(data, fname)
                return data
            return jsonload(fname)

        if sid not in self._data:
            try:
                self._data[sid] = self.get_info(id)
            except:
                return
        return self._data[sid]

    def update(self, taxon, data):
        raise NotImplementedError()

    def update_taxon(self, taxon):
        # Try to find a provider-specific ID:
        if not taxon[self.name + '_id']:
            taxon[self.name + '_id'] = self.get_id(taxon['name'])
        if not taxon[self.name + '_id']:
            return False

        # Use this ID to fetch new data in case nothing is cached for sid:
        data = self.get_cached(taxon['id'], taxon[self.name + '_id'])
        if data:
            self.update(taxon, data)
            return True
        return False

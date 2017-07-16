#!/usr/bin/env python
"""
ADS to BibDesk -- frictionless import of ADS publications into BibDesk
Copyright (C) 2014  Rui Pereira <rui.pereira@gmail.com> and
                    Jonathan Sick <jonathansick@mac.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

Based on ADS to Bibdesk automator action by
Jonathan Sick, jonathansick@mac.com, August 2007

Input may be one of the following:
- ADS abstract page URL
- ADS bibcode
- arXiv abstract page
- arXiv identifier
"""
import datetime
import difflib
import fnmatch
import glob
import logging
import math
import optparse
import os
import pprint
import re
import socket
import sys
import tempfile
import time

# cgi.parse_qs is deprecated since 2.6
# but OS X 10.5 only has 2.5
import cgi
import urllib2
import urlparse

import subprocess as sp
try:
    import AppKit
except ImportError:
    # is this not the system python?
    syspath = eval(sp.Popen('/usr/bin/python -c "import sys; print(sys.path)"',
                            shell=True, stdout=sp.PIPE).stdout.read())
    for p in syspath:
        if os.path.isdir(p) and glob.glob(os.path.join(p, '*AppKit*')):
            sys.path.insert(0, p)
            break

    # retry
    try:
        import AppKit
    except ImportError:
        import webbrowser
        url = 'http://pythonhosted.org/pyobjc/install.html'
        msg = 'Please install PyObjC...'
        print msg
        sp.call(r'osascript -e "tell application \"System Events\" to '
                'display dialog \"%s\" buttons {\"OK\"} default button \"OK\""'
                % msg, shell=True, stdout=open('/dev/null', 'w'))
        # open browser in PyObjC install page
        webbrowser.open(url)
        sys.exit()

from HTMLParser import HTMLParser, HTMLParseError
from htmlentitydefs import name2codepoint

class CDSParser(object):

    def __init__(self):
        """
        Parse CERN Document Server information for a *single* ID

        :param CDS_id: arXiv identifier
        """
        pass

    def parse_at_id(self, arxiv_id):
        """Helper method to read data from URL, and passes on to parse()."""
        from xml.etree import ElementTree
        self.url = 'https://cds.cern.ch/search?ln=en&p=reportnumber%3A"' + arxiv_id '"&action_search=Search&op1=a&m1=a&p1=&f1=&c=CERN+Document+Server&sf=&so=d&rm=&rg=10&sc=1&of=xm'
        try:
            self.xml = ElementTree.fromstring(urllib2.urlopen(self.url).read())
        except (urllib2.HTTPError, urllib2.URLError), err:
            logging.debug("ArXivParser failed on URL: %s", self.url)
            raise ArXivException(err)
        self.info = self.parse(self.xml)
        self.bib = self.bibtex(self.info)  # FIXME looks like self.bib is None

    def parse(self, xml):
        # recursive xml -> list of (tag, info)
        getc = lambda e: [
            (c.tag.split('}')[-1], c.getchildren() and
                dict(getc(c)) or (c.text is not None and re.sub('\s+', ' ',
                                  c.text.strip()) or c.attrib))
            for c in e.getchildren()]

        # article info
        info = {}
        for k, v in getc(xml.getchildren()[-1]):  # last item is article
            if isinstance(v, dict):
                info.setdefault(k, []).append(v)
            else:
                info[k] = v
        return info

    def bibtex(self, info):
        """
        Create BibTex entry. Sets a bunch of "attributes" that are used
        explictly on __str__ as BibTex entries

        :param info: parsed info dict from arXiv
        """
        # TODO turn these into properties?
        self.Author = ' and '.join(
            ['{%s}, %s' % (a['name'].split()[-1],
                           '~'.join(a['name'].split()[:-1]))
             for a in info['author']
             if len(a['name'].strip()) > 1]).encode('utf-8')
        self.Title = info['title'].encode('utf-8')
        self.Abstract = info['summary'].encode('utf-8')
        self.AdsComment = info['comment'].replace('"', "'").encode('utf-8') \
            if 'comment' in info else ""
        self.Jornal = 'ArXiv e-prints'
        self.ArchivePrefix = 'arXiv'
        self.ArXivURL = info['id']
        self.Eprint = info['id'].split('abs/')[-1]
        self.PrimaryClass = info['primary_category'][0]['term']
        self.Year, self.Month = datetime.datetime.strptime(
            info['published'],
            '%Y-%m-%dT%H:%M:%SZ').strftime('%Y %b').split()

    def __str__(self):
        import string
        return '@article{%s,\n' % self.Eprint +\
            '\n'.join([
                '%s = {%s},' % (k, v)
                for k, v in
                sorted([(k, v.decode('utf-8'))
                        for k, v in self.__dict__.iteritems()
                        if k[0] in string.uppercase])]) +\
            '}'

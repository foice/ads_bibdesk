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
#from lxml import etree as ET


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

def find_recid_in_xml(xml):
    recid = xml.find(".//*[@tag='001']").text
    logging.debug(' Found RECID %s ' % recid)
    return recid

def find_pdf_in_xml(xml):

    for pdfurl in xml.findall(".//*[@tag='856']"):
        if pdfurl.find("./*[@code='y']") is not None:
            if "Fulltext" in pdfurl.find("./*[@code='y']").text:
                for found in pdfurl.findall("./*[@code='u']"):
                    if ".pdf" in found.text:
                        return found.text
    for pdfurl in xml.findall(".//*[@tag='856']/*[@code='u']"):
        if ".pdf" in pdfurl.text:
            return pdfurl.text
    return ''


def find_title_in_xml(xml):
    return xml.find(".//*[@tag='245']/*[@code='a']").text


def find_journal_in_xml(xml):
    try:
        journal = xml.find(".//*[@tag='773']/*[@code='p']").text
        return journal
    except AttributeError:
        try:
            journal = xml.find(".//*[@tag='037']/*[@code='a']").text
            return journal
        except AttributeError:
            return ''

def find_DOI_in_xml(xml):
    try:
        res =  xml.find(".//*[@tag='024']/*[@code='a']").text
        logging.debug('DOI %s' % res)
        return res
    except AttributeError:
        return ''

def find_pages_in_xml(xml):
    try:
        res = xml.find(".//*[@tag='773']/*[@code='c']").text
        return res
    except AttributeError:
        return ''

def find_publication_volume_in_xml(xml):
    try:
        res = xml.find(".//*[@tag='773']/*[@code='v']").text
        return res
    except AttributeError:
        return ''

def find_publication_volume_number_in_xml(xml):
    try:
        res = xml.find(".//*[@tag='773']/*[@code='n']").text
        return res
    except AttributeError:
        return ''

def find_publication_year_in_xml(xml):
    try:
        res = xml.find(".//*[@tag='773']/*[@code='y']").text
        return res
    except AttributeError:
        return ''

def find_abstract_in_xml(xml):
    return xml.find(".//*[@tag='520']/*[@code='a']").text


def find_author_in_xml(xml):
    def TeXify(first_author):
        texified = '{%s}, %s' % (first_author.strip().split(',')[0],
                   '~'.join(first_author.strip().split(',')[1:]))
        return texified

    first_author = xml.find(".//*[@tag='100']/*[@code='a']").text
    formatted_first_author = TeXify(first_author)

    logging.debug('FIRST AUTHOR %s' % first_author)
    logging.debug( formatted_first_author )
    further_authors = [ TeXify(_a.text) for _a in xml.findall(".//*[@tag='700']/*[@code='a']")]

    authors = [formatted_first_author]+further_authors
    authors_string = ' and '.join(authors)
    return authors_string

def find_eprint_in_xml(xml):
    try:
        # go for the arXiv eprint
        eprint = xml.find(".//*[@tag='037']/*[@code='a']").text
        logging.debug("eprint found %s" % eprint)
        return eprint
    except:
        try:
            # go for Inspires eprint
            eprint = xml.find(".//*[@tag='035']/*[@code='a']").text
            logging.debug("eprint found %s" % eprint)
            return eprint
        except:
            return find_recid_in_xml(self.xml)

def find_how_many_authors_in_xml(xml):
    return len(xml.findall(".//*[@tag='700']/*[@code='a']"))

def find_collaboration_in_xml(xml):
    if xml.find(".//*[@tag='110']/*[@code='a']") is not None:
        return xml.find(".//*[@tag='110']/*[@code='a']").text
    if xml.find(".//*[@tag='710']/*[@code='g']") is not None:
        return xml.find(".//*[@tag='710']/*[@code='g']").text


class CDSbibtex(object):

    def __init__(self):
        """
        Parse CERN Document Server information for a *single* ID

        :param CDS_id: arXiv identifier
        """
        pass

    def __str__(self):
        import string
        result='@article{%s,\n' % self.Eprint
        result= result + 'eprint = \"%s\",\n' % self.Eprint
        result= result + 'number = \"%s\",\n' % self.Eprint
        result= result + 'title = \"{%s}\",\n' % self.Title
        result= result + 'journal = \"{%s}\",\n' % self.Journal
        result= result + 'volume = \"{%s}\",\n' % self.Volume
        result= result + 'number = \"{%s}\",\n' % self.number
        result= result + 'pages = \"{%s}\",\n' % self.Pages
        result= result + 'year = \"{%s}\",\n' % self.Year
        #result= result + 'collaboration = \"{%s}\",\n' % self.Author
        result= result + 'author = \"{%s}\",\n' % self.Author
        result= result + 'url = \"%s\",\n' % self.Url
        result= result + 'doi = \"%s\",\n' % self.doi
        result= result + '}'
        return result



class CDSParser(object):

    def __init__(self):
        """
        Parse CERN Document Server information for a *single* ID

        :param CDS_id: arXiv identifier
        """
        pass

    def parse_at_id(self, arxiv_id,server='CDS'):
        """Helper method to read data from URL, and passes on to parse()."""
        from xml.etree import ElementTree
        if server=='CDS':
            logging.debug('requested server for MARCXML is %s ' % server)
            self.url = 'https://cds.cern.ch/search?ln=en&p=reportnumber%3A"' + arxiv_id + '"&action_search=Search&op1=a&m1=a&p1=&f1=&c=CERN+Document+Server&sf=&so=d&rm=&rg=10&sc=1&of=xm'
            ads_url_base = 'https://cds.cern.ch/record/'

        if server =='Inspires':
            logging.debug('requested server for MARCXML is %s ' % server)
            self.url='https://inspirehep.net/search?ln=en&p=recid+'+arxiv_id+'&of=xm'
            ads_url_base =  'https://inspirehep.net/record/'
        try:
            self.xml = ElementTree.fromstring(urllib2.urlopen(self.url).read())
        except (urllib2.HTTPError, urllib2.URLError), err:
            logging.debug("Could not get MARCXML from URL: %s", self.url)
            raise ArXivException(err)

        if find_recid_in_xml(self.xml)>0:
            logging.debug('recid found')
            self.bibtex(self.xml,server=server)
            self.ads_url = ads_url_base + self.recid + "/"

            #print getattr(self.bib, 'Title')
            #pdf_url = find_pdf_in_xml(self.xml)
            #self.pdf_url = pdf_url
            #print "recid ", find_recid_in_xml(self.xml), " found. It's a CDS!"
            #print "title ", self.title
            #print "eprint ", self.eprint
            #print "abstract ", self.abstract
            #print "collaboration", self.author
            #print "url", self.ads_url
        #self.info = self.parse(self.xml)
        #self.bib = self.bibtex(self.info)  # FIXME looks like self.bib is None

    def bibtex(self,xml,server='CDS'):

        print 'Called the cds.bibtex method with options server=',server
        print xml 
        bibentry = CDSbibtex()
        bibentry.Eprint = find_eprint_in_xml(xml)
        logging.debug('Filled with EPRINT %s ' % bibentry.Eprint)

        bibentry.recid = find_recid_in_xml(xml)
        self.recid=bibentry.recid

        if server=='CDS':
            bibentry.Author = find_collaboration_in_xml(xml)
            bibentry.Journal = 'CERN Note'
            baseUSL= 'https://cds.cern.ch/record/'
        if server=='Inspires':
            bibentry.Author = find_author_in_xml(xml)
            bibentry.Journal = find_journal_in_xml(xml)
            baseUSL= 'https://inspirehep.net/record/'

        bibentry.Year = find_publication_year_in_xml(xml)
        bibentry.Volume = find_publication_volume_in_xml(xml)
        bibentry.Pages = find_pages_in_xml(xml)
        bibentry.number = find_publication_volume_number_in_xml(xml)
        bibentry.doi = find_DOI_in_xml(xml)

        url = baseUSL + self.recid + "/"
        bibentry.Url = url

        bibentry.Title = find_title_in_xml(xml)
        bibentry.Abstract = find_abstract_in_xml(xml)
        bibentry.AdsComment = ''

        info={}
        info['link']=find_pdf_in_xml(xml)
        bibentry.info = info
        #
        self.bib=bibentry


    def parse(self, xml):
        # recursive xml -> list of (tag, info)
        #getc = lambda e: [
        #    (c.tag.split('}')[-1], c.getchildren() and
        #        dict(getc(c)) or (c.text is not None and re.sub('\s+', ' ',
        #                          c.text.strip()) or c.attrib))
        #    for c in e.getchildren()]


        pdf_url = find_pdf_in_xml(xml)
        recid = find_recid_in_xml(xml)
        print recid
        print pdf_url
        print('-------------------------')

        # article info
        info = {}
        for k, v in getc(xml.getchildren()[-1]):  # last item is article
            #print(k)
            if isinstance(v, dict):
                info.setdefault(k, []).append(v)
            else:
                info[k] = v
        return info

    # def bibtex(self, info):
    #     """
    #     Create BibTex entry. Sets a bunch of "attributes" that are used
    #     explictly on __str__ as BibTex entries
    #
    #     :param info: parsed info dict from arXiv
    #     """
    #     # TODO turn these into properties?
    #     self.Author = ' and '.join(
    #         ['{%s}, %s' % (a['name'].split()[-1],
    #                        '~'.join(a['name'].split()[:-1]))
    #          for a in info['author']
    #          if len(a['name'].strip()) > 1]).encode('utf-8')
    #     self.Title = info['title'].encode('utf-8')
    #     self.Abstract = info['summary'].encode('utf-8')
    #     self.AdsComment = info['comment'].replace('"', "'").encode('utf-8') \
    #         if 'comment' in info else ""
    #     self.Journal = 'ArXiv e-prints'
    #     self.ArchivePrefix = 'arXiv'
    #     self.ArXivURL = info['id']
    #     self.Eprint = info['id'].split('abs/')[-1]
    #     self.PrimaryClass = info['primary_category'][0]['term']
    #     self.Year, self.Month = datetime.datetime.strptime(
    #         info['published'],
    #         '%Y-%m-%dT%H:%M:%SZ').strftime('%Y %b').split()

    def __str__(self):
        import string
        return '@article{%s,\n' % self.Eprint+'}'
        # +\
        #    '\n'.join([
        #        '%s = {%s},' % (k, v)
        #        for k, v in
        #        sorted([(k, v.decode('utf-8'))
        #                for k, v in self.__dict__.iteritems()
        #                if k[0] in string.uppercase])]) +\
        #    '}'


#cds_id='CMS-PAS-SMP-17-004'
#cds_id='CMS-PAS-HIG-16-027'
#print('working on '+cds_id)
#cds_bib = CDSParser()
#cds_bib.parse_at_id(cds_id)

#try:
#except ArXivException, err:
#    print('error')

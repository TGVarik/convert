from __future__ import unicode_literals
from logging import getLogger
import sys
if sys.version > '3':
  from urllib.request import Request, urlopen
else:
  from urllib2 import Request, urlopen
from xml.dom import minidom
from config import config

def refresh_plex(host='atlas', source_type='show'):
  log = getLogger()
  log.debug('Refreshing Plex...')
  base_url = 'http://{:s}:32400/library/sections'.format(host)
  try:
    lib_request = Request(base_url, headers={'X-Plex-Token':config['plex_token']})
    xml_sections = minidom.parse(urlopen(lib_request))
    sections = xml_sections.getElementsByTagName('Directory')
    for s in sections:
      if s.getAttribute('type') == source_type:
        url = '{:s}/{:s}/refresh'.format(base_url, s.getAttribute('key'))
        refresh_request = Request(url, headers={'X-Plex-Token':config['plex_token']})
        x = urlopen(refresh_request)
        if x.getcode() == 200:
          log.info('Plex refresh succeeded with return code: {:d}'.format(x.getcode()))
        else:
          log.warn('Plex refresh failed with return code: {:d}'.format(x.getcode()))
  except Exception as e:
    log.warn('Refreshing Plex failed with {:s}: {:s}'.format(type(e).__name__, e))

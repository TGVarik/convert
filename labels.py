#!/usr/bin/env python
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
from twisted.internet import reactor
from deluge.ui.client import client
from config import config
from logs import setup_logging

class Fakelog():
  def __init__(self):
    self.error = print
    self.debug = print

log = Fakelog()

def cleanup():
  client.disconnect()
  reactor.stop()

def on_get_mgr(result):
  log.debug(repr(result))
  cleanup()

def on_connect_success(result):
  log.debug('Connected to daemon with result {:d}'.format(result))
  log.debug ('Fetching Label plugin...')
  d = client.core.__getattr__('pluginmanager')
  d.addCallback(on_get_mgr)
  d.addErrback(on_fail)

def on_fail(result):
  log.error('Failed with result {}'.format(result))
  cleanup()

def on_connect_fail(result):
  log.error('Failed to connect to daemon - {}'.format(repr(result)))
  reactor.stop()


d = client.connect(host='acromantula', username='flexget', password='flexgetdeluge')
d.addCallback(on_connect_success)
d.addErrback(on_connect_fail)
reactor.run()
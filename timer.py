from __future__ import unicode_literals

from time import time
from logging import getLogger, LoggerAdapter

class Timer:
  def __init__(self, action, id=None):
    self.start = None
    self.end = None
    self.interval = None
    self.action = action
    self.log = getLogger()
    if id:
      self.log = LoggerAdapter(self.log, {'identifier': id})

  def __enter__(self):
    self.log.debug(self.action + '...')
    self.start = time()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.end = time()
    self.interval = self.end - self.start
    self.log.info('{:s} took {:.02f} seconds'.format(self.action, self.interval))
    return False

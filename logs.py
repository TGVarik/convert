from __future__ import unicode_literals

from logging import getLogger, DEBUG, FileHandler, Formatter, Filter
from datetime import datetime
from tzlocal import get_localzone
import pytz
import sys
import re

def setup_logging(name):
  logger = getLogger()
  logger.setLevel(DEBUG)
  fh = FileHandler('{:s}.log'.format(name))
  fh.setLevel(DEBUG)
  fm = CustomFormatter(fmt='{asctime:s} {identifier:14s}[ {levelname:^8s} ]:{msg:s}')
  fh.setFormatter(fm)
  fh.addFilter(LogFilter())
  logger.addHandler(fh)

class LogFilter(Filter):
  def filter(self, record):
    if record.name != 'root':
      return False
    else:
      return True


class CustomFormatter(Formatter):
  def __init__(self, **kwargs):
    super(CustomFormatter, self).__init__(**kwargs)
    self._fmt = kwargs['fmt'] if 'fmt' in kwargs else '{message:s}'
  def formatTime(self, record, datefmt=None):
    ct = datetime.utcfromtimestamp(record.created).replace(tzinfo=pytz.UTC)
    lz = get_localzone()
    dt = ct.astimezone(lz)
    if datefmt:
      s = dt.strftime(datefmt)
    else:
      s = '{:s},{:03d}{:s}'.format(dt.strftime('%Y-%m-%dT%H:%M:%S'),int(dt.microsecond/1000),dt.strftime('%z'))
    return s
  def usesTime(self):
    return self._fmt.find('{asctime') >= 0
  def format(self, record):
    record.message = record.getMessage()
    if self.usesTime():
      record.asctime = self.formatTime(record, self.datefmt)
    fmt = self._fmt
    identifier_index = fmt.find('{identifier')
    if identifier_index >= 0:
      if 'identifier' not in record.__dict__:
        fmt = re.sub('\{identifier.*?\}','              ',fmt)
    s = fmt.format(**record.__dict__)
    if record.exc_info:
      if not record.exc_text:
        record.exc_text = self.formatException(record.exc_info)
    if record.exc_text:
      if s[-1:] != '\n':
        s += '\n'
      try:
        s += record.exc_text
      except UnicodeError:
        s = s + record.exc_text.decode(sys.getfilesystemencoding(), 'replace')
    return s

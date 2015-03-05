from __future__ import unicode_literals
import tempfile
from logging import getLogger, LoggerAdapter
from email.mime.text import MIMEText
from smtplib import SMTP
from pushover import init, Client
import os
from traceback import print_exception, format_exception
from config import config

from timer import Timer



def pushover(s, m, fail=False):
  init(config['pushover_dev'])
  for k in config['pushover_users']:
    if fail:
      Client(user_key=k).send_message(m, title=s, priority=1, sound='falling')
    else:
      Client(user_key=k).send_message(m, title=s)

class Cleaner(object):
  def __init__(self, ref, id=None, temp_dir=None):
    if temp_dir:
      tempfile.tempdir = temp_dir
    self._temp_files = []
    self.temp_dir = tempfile.gettempdir()
    self._ref = ref
    self._log = getLogger()
    self._id = id
    if id:
      self._log = LoggerAdapter(self._log, {'identifier': id})

  def __enter__(self):
    return self

  def add_path(self, path):
    if path not in self._temp_files:
      self._temp_files.append(path)

  def timer_pushover(self, t):
    pushover(self._ref, '{:s} took {:.02f} seconds.'.format(t.action, t.interval))

  def send_failmail(self, subject, body, to_address='tgvarik@me.com'):
    from_address = config['email']
    email_password = config['password']
    self._log.debug('Sending failmail...')
    con = None
    try:
      msg = MIMEText(body)
      msg['Subject'] = subject
      msg['From'] = from_address
      msg['To'] = to_address
      con = SMTP()
      con.set_debuglevel(1)
      con.connect('smtp.mail.me.com', 587)
      con.starttls()
      con.ehlo()
      con.login(user=from_address, password=email_password)
      con.sendmail(from_addr=from_address, to_addrs=[to_address], msg=msg.as_string())
    except Exception as e:
      self._log.error('Sending failmail failed! Logging message...')
      self._log.error(subject)
      self._log.error(body)
    finally:
      if con is not None:
        con.close()

  def __exit__(self, exc_type, exc_val, exc_tb):
    if len(self._temp_files) > 0:
      with Timer('Cleaning up', self._id):
        for f in self._temp_files:
          if os.path.exists(f):
            self._log.debug('Deleting temp file {:s}'.format(f))
            os.remove(f)
    if exc_val is not None:
      self.send_failmail(self._ref, ''.join(format_exception(exc_type, exc_val, exc_tb)))
      pushover(self._ref, 'An error of type {:s} occurred: {}'.format(exc_type.__name__, exc_val), True)
      print_exception(exc_type, exc_val, exc_tb)
    return False

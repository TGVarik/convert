import os
from subprocess import call
from ffmpeg import get_ffprobe, _command_to_string

files = []
for root, dirs, fs in os.walk('/tank/Incoming'):
  files.extend([os.path.join(root, f) for f in fs if
                os.path.splitext(f)[1].lower() in ['.mkv', '.done']])
for f in files:
  ffprobe = get_ffprobe(f)
  sub_streams = [s for s in ffprobe['streams'] if s['codec_type'] == 'subtitle' and s['codec_name'] in ['pgssub', 'dvdsub']]
  if len(sub_streams) > 0:
    cmd = ['ffmpeg', '-hide_banner', '-stats', '-y', '-v', 'quiet', '-i', f]
    maps = []
    codecs = []
    sub_index = -1
    basename = os.path.splitext(os.path.basename(f))
    if basename[1].lower() == '.done':
      basename = os.path.splitext(basename[0])
    outfile = os.path.join('/tank/subs', '.'.join([basename[0], 'subs', 'mkv']))
    if not os.path.exists(outfile):
      for stream in sub_streams:
        sub_index += 1
        maps.extend(['-map', '0:{:d}'.format(stream['index'])])
        codecs.extend(['-c:s:{:d}'.format(sub_index), 'copy'])
      cmd.extend(maps)
      cmd.extend(codecs)
      cmd.extend(['-f', 'matroska', outfile])
      print(_command_to_string(cmd).encode('latin-1'))
      p = call(cmd)
      if p != 0:
        raise IOError('Failure with exit code: {:d}'.format(p))
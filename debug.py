import re
import os

folder = '/tank/Incoming'
searcher = re.compile(r'^(\[(?P<collection>[^\]]+)\]\s*)?(?P<tmdb_id>\d+)\s?-(?P<title>.+?)$')
files = []
for root, dirs, fs in os.walk(folder):
  files.extend([os.path.join(root, f) for f in fs if
                os.path.splitext(f)[1].lower() in ['.mkv', '.mp4', '.avi'] and
                searcher.search(os.path.splitext(os.path.basename(f))[0]) is not None])
print('{:d} files found.'.format(len(files)))

for f in sorted(files, key=lambda f: int(searcher.search(os.path.splitext(os.path.basename(f))[0]).group('tmdb_id'))):
  match = searcher.search(os.path.splitext(os.path.basename(f))[0])
  if match:
    print(f)
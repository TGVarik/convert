# coding=utf-8
# import os
import re
from subprocess import Popen, PIPE

# def get_file_version(filepath):
#   if os.path.isfile(filepath):
#     cmd = ['AtomicParsley', filepath, '-t']
#     version_matcher = re.compile(r'Atom\suuid=0c5c9153-0bd4-5e72-be75-92dfec8ab00c\s\(AP\suuid\sfor\s\"Â©inf\"\)\scontains:\sFFver(?P<version>\d+\.\d+\.\d+)', re.I)
#     p = Popen(cmd, stdout=PIPE, stderr=PIPE)
#     out, _ = p.communicate()
#     found = version_matcher.search(out.decode('latin-1'))
#     if found:
#       return found.groupdict()['version']
#   return None

cmd = ['AtomicParsley', '/tank/Plex/Movies/Lord of the Rings/The Lord of the Rings The Two Towers (2002)/The Lord of the Rings The Two Towers (2002).480p.v.mp4', '-t']
p = Popen(cmd, stdout=PIPE, stderr=PIPE)
out, _ = p.communicate()

li = (n for n in out.decode('latin-1').split('\n') if n[0:5] == 'Atom')

tupleRE = ('Atom','\s','uuid=0c5c9153-0bd4-5e72-be75-92dfec8ab00c','\s','\(','AP','\s','uuid','\s','for','\s','\"','Â','©','inf','\"','\)','\s','contains:','\s','FFver','(?P<version>\d+\.\d+\.\d+)')

def REtest(ch, tuplRE, flags = re.MULTILINE):
    for n in xrange(len(tupleRE)):
        regx = re.compile(''.join(tupleRE[:n+1]), flags)
        testmatch = regx.search(ch)
        if not testmatch:
            print '\n  -*- tupleRE :\n'
            print '\n'.join(str(i).zfill(2)+' '+repr(u)
                            for i,u in enumerate(tupleRE[:n]))
            print '   --------------------------------'
            # tupleRE doesn't works because of element n
            print str(n).zfill(2)+' '+repr(tupleRE[n])\
                  +"   doesn't match anymore from this ligne "\
                  +str(n)+' of tupleRE'
            print '\n'.join(str(n+1+j).zfill(2)+' '+repr(u)
                            for j,u in enumerate(tupleRE[n+1:
                                                         min(n+2,len(tupleRE))]))

            for i in xrange(n):
                match = re.search(''.join(tupleRE[:n-i]),ch, flags)
                if match:
                    break

            matching_portion = match.group()
            matching_li = '\n'.join(map(repr,
                                        matching_portion.splitlines(True)[-5:]))
            fin_matching_portion = match.end()
            print ('\n\n  -*- Part of the tested string which is concerned :\n\n'
                   '######### matching_portion ########\n'+matching_li + '\n'
                   '##### end of matching_portion #####\n'
                   '-----------------------------------\n'
                   '######## unmatching_portion #######')
            print '\n'.join(map(repr,
                                ch[fin_matching_portion:
                                   fin_matching_portion+300].splitlines(True)) )
            break
    else:
        print '\n  SUCCES . The regex integrally matches.'

for x in li:
    print '  -*- Analyzed string :\n%r' % x
    REtest(x,tupleRE)
    print '\nmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwmwm'
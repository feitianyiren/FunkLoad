# (C) Copyright 2005 Nuxeo SAS <http://nuxeo.com>
# Author: bdelbosc@nuxeo.com
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
# 02111-1307, USA.
#
"""Simple FunkLoad Test Recorder.

require tcpwatch.py
* http://hathawaymix.org/Software/TCPWatch/tcpwatch-1.3.tar.gz

Credits goes to Ian Bicking for parsing tcpwatch files.

$Id$
"""
import os
import sys
import re
from cStringIO import StringIO
from optparse import OptionParser, TitledHelpFormatter
from tempfile import mkdtemp
import rfc822
from cgi import FieldStorage
from urlparse import urlsplit
from utils import truncate, trace, get_version

class Request:
    """Store a tcpwatch request."""
    def __init__(self, file_path):
        """Load a tcpwatch request file."""
        self.file_path = file_path
        f = open(file_path, 'rb')
        line = f.readline().split(None, 2)
        self.method = line[0]
        url = line[1]
        scheme, host, path, query, fragment = urlsplit(url)
        self.host = scheme + '://' + host
        self.rurl = url[len(self.host):]
        self.url = url
        self.path = path
        self.version = line[2].strip()
        self.headers = dict(rfc822.Message(f).items())
        self.body = f.read()
        f.close()

    def extractParam(self):
        """Turn muti part encoded form into params."""
        environ = {
            'CONTENT_TYPE': self.headers['content-type'],
            'CONTENT_LENGTH': self.headers['content-length'],
            'REQUEST_METHOD': 'POST',
            }
        form = FieldStorage(fp=StringIO(self.body),
                            environ=environ,
                            keep_blank_values=True)
        params = []
        for key in form.keys():
            if not isinstance(form[key], list):
                values = [form[key]]
            else:
                values = form[key]
            for form_value in values:
                filename = form_value.filename
                if filename is None:
                    params.append([key, form_value.value])
                else:
                    # got a file upload
                    filename = filename or 'empty.txt'
                    params.append([key, 'Upload("%s")' % filename])
                    if os.path.exists(filename):
                        trace('# Warning: uploaded file: %s already exists, '
                              'keep it.\n' % filename)
                    else:
                        trace('# Saving uploaded file: %s\n' % filename)
                        f = open(filename, 'w')
                        f.write(str(form_value.value))
                        f.close()
        return params

    def __repr__(self):
        params = ''
        if self.body:
            params = self.extractParam()
        return '<request method="%s" url="%s" %s/>' % (
            self.method, self.url, str(params))


class Response:
    """Store a tcpwatch response."""
    def __init__(self, file_path):
        """Load a tcpwatch response file."""
        self.file_path = file_path
        f = open(file_path, 'rb')
        line = f.readline().split(None, 2)
        self.version = line[0]
        self.status_code = line[1].strip()
        if len(line) > 2:
            self.status_message = line[2].strip()
        else:
            self.status_message = ''
        self.headers =  dict(rfc822.Message(f).items())
        self.body = f.read()
        f.close()

    def __repr__(self):
        return '<response code="%s" type="%s" status="%s" />' % (
            self.status_code, self.headers.get('content-type'),
            self.status_message)


class RecorderProgram:
    """A tcpwatch to funkload recorder."""
    USAGE = """%prog [options]

%prog launch a TCPWatch proxy and record activities, then output a FunkLoad
script or generates a FunkLoad unit test.
The default proxy port is 8090.

Note that tcpwatch.py executable must be accessible from your env.

See http://funkload.nuxeo.org/ for more information.

Examples
========

  %prog -p 9090             - run a proxy on port 9090, output script
                              to stdout
  %prog -o foo_bar          - run a proxy and create a FunkLoad test
                              case, generates test_FooBar.py and
                              FooBar.conf file. To test it:
                              fl-run-test -dV test_FooBar.py
  %prog -i /tmp/tcpwatch    - convert a tcpwatch capture into a script
"""
    def __init__(self, argv=None):
        if argv is None:
            argv = sys.argv[1:]
        self.verbose = False
        self.tcpwatch_path = None
        self.prefix = 'watch'
        self.port = "8090"
        self.server_url = None
        self.class_name = None
        self.test_name = None
        self.script_path = None
        self.configuration_path = None
        self.parseArgs(argv)

    def parseArgs(self, argv):
        """Parse programs args."""
        parser = OptionParser(self.USAGE, formatter=TitledHelpFormatter(),
                              version="FunkLoad %s" % get_version())
        parser.add_option("-v", "--verbose", action="store_true",
                          help="Verbose output")
        parser.add_option("-p", "--port", type="string", dest="port",
                          default=self.port, help="The proxy port.")
        parser.add_option("-i", "--tcp-watch-input", type="string",
                          dest="tcpwatch_path", default=None,
                          help="Path to an existing tcpwatch capture.")
        parser.add_option("-o", "--output", type="string",
                          dest="test_name",
                          help="Create a FunkLoad script and conf file.")
        options, args = parser.parse_args(argv)
        self.verbose = options.verbose
        self.tcpwatch_path = options.tcpwatch_path
        self.port = options.port
        test_name = options.test_name
        if test_name:
            class_name = ''.join([x.capitalize()
                                  for x in re.split('_|-', test_name)])
            self.test_name = test_name
            self.class_name = class_name
            self.script_path = './test_%s.py' % class_name
            self.configuration_path = './%s.conf' % class_name


    def startProxy(self):
        """Start a tcpwatch session."""
        self.tcpwatch_path = mkdtemp('_funkload')
        cmd = 'tcpwatch.py -p %s -s -r %s' % (self.port,
                                              self.tcpwatch_path)
        if self.verbose:
            cmd += ' | grep "T http"'
        else:
            cmd += ' > /dev/null'
        trace("Hit Ctrl-C to stop recording.\n")
        os.system(cmd)

    def searchFiles(self):
        """Search tcpwatch file."""
        items = {}
        prefix = self.prefix
        for filename in os.listdir(self.tcpwatch_path):
            if not filename.startswith(prefix):
                continue
            name, ext = os.path.splitext(filename)
            name = name[len(self.prefix):]
            ext = ext[1:]
            if ext == 'errors':
                trace("Error in response %s" % name)
                continue
            assert ext in ('request', 'response'), "Bad extension: %r" % ext
            items.setdefault(name, {})[ext] = os.path.join(
                self.tcpwatch_path, filename)
        items = items.items()
        items.sort()
        return [(v['request'], v['response'])
                for name, v in items
                if v.has_key('response')]

    def extractRequests(self, files):
        """Filter and extract request from tcpwatch files."""
        last_code = None
        filter_ctypes = ('image', 'css', 'javascript')
        filter_url = ('.jpg', '.png', '.gif', '.css', '.js')
        requests = []
        for request_path, response_path in files:
            response = Response(response_path)
            request = Request(request_path)
            if self.server_url is None:
                self.server_url = request.host
            host = request.host
            ctype = response.headers.get('content-type', '')
            url = request.url
            if request.method != "POST" and (
                last_code in ('301', '302') or
                [x for x in filter_ctypes if x in ctype] or
                [x for x in filter_url if url.endswith(x)]):
                last_code = response.status_code
                continue
            last_code = response.status_code
            requests.append(request)
        return requests

    def reindent(self, code, indent=8):
        """Improve indentation."""
        spaces = ' ' * indent
        code = code.replace('], [', '],\n%s    [' % spaces)
        code = code.replace('[[', '[\n%s    [' % spaces)
        code = code.replace(', description=', ',\n%s    description=' % spaces)
        code = code.replace('self.', '\n%sself.' % spaces)
        return code

    def convertToFunkLoad(self, request):
        """return a funkload python instruction."""
        text = []
        server_url = self.server_url
        if request.host != self.server_url:
            text.append('self.%s("%s"' % (request.method.lower(),
                                          request.url))
        else:
            text.append('self.%s("%%s%s" %% server_url' % (
                request.method.lower(),  request.rurl))
        description = "%s %s" % (request.method.capitalize(),
                                 request.path | truncate(42))
        if request.body:
            params =('params=%s' % request.extractParam())
            params = re.sub("'Upload\(([^\)]*)\)'", "Upload(\\1)", params)
            text.append(', ' + params)
        text.append(', description="%s")' % description)
        return ''.join(text)

    def extractScript(self):
        """Convert a tcpwatch capture into a FunkLoad script."""
        files = self.searchFiles()
        requests = self.extractRequests(files)
        code = [self.convertToFunkLoad(request)
                for request in requests]
        if not code:
            trace("Sorry no action recorded.\n")
            return
        code.insert(0, '')
        return self.reindent('\n'.join(code))

    def writeScript(self, script):
        """Write the FunkLoad test script."""
        trace('Creating script: %s.\n' % self.script_path)
        from pkg_resources import resource_string
        tpl = resource_string('funkload', 'data/ScriptTestCase.tpl')
        content = tpl % {'script': script,
                         'test_name': self.test_name,
                         'class_name': self.class_name}
        if os.path.exists(self.script_path):
            trace("Error file %s already exists.\n" % self.script_path)
            return
        f = open(self.script_path, 'w')
        f.write(content)
        f.close()

    def writeConfiguration(self):
        """Write the FunkLoad configuration test script."""
        trace('Creating configuration file: %s.\n' % self.configuration_path)
        from pkg_resources import resource_string
        tpl = resource_string('funkload', 'data/ConfigurationTestCase.tpl')
        content = tpl % {'server_url': self.server_url,
                         'test_name': self.test_name,
                         'class_name': self.class_name}
        if os.path.exists(self.configuration_path):
            trace("Error file %s already exists.\n" %
                  self.configuration_path)
            return
        f = open(self.configuration_path, 'w')
        f.write(content)
        f.close()

    def run(self):
        """run it."""
        if self.tcpwatch_path is None:
            self.startProxy()
        script = self.extractScript()
        if not script:
            return
        if self.test_name is not None:
            self.writeScript(script)
            self.writeConfiguration()
        else:
            print script

if __name__ == '__main__':
    RecorderProgram().run()
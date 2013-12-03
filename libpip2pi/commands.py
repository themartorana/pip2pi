import os
import sys
import cgi
import shutil
import atexit
#import zipfile
import tempfile
import textwrap
import functools
from subprocess import check_call
import pkg_resources
import glob
import hashlib

def dedent(text):
    return textwrap.dedent(text.lstrip("\n"))

def maintain_cwd(f):
    @functools.wraps(f)
    def maintain_cwd_helper(*args, **kwargs):
        orig_dir = os.getcwd()
        try:
            return f(*args, **kwargs)
        finally:
            os.chdir(orig_dir)
    return maintain_cwd_helper

def egg_to_package(file):
    """ Extracts the package name from an egg.

        >>> egg_to_package("PyYAML-3.10-py2.7-macosx-10.7-x86_64.egg")
        ('PyYAML', '3.10-py2.7-macosx-10.7-x86_64.egg')
        >>> egg_to_package("python_ldap-2.3.9-py2.7-macosx-10.3-fat.egg")
        ('python-ldap', '2.3.9-py2.7-macosx-10.3-fat.egg')
    """
    dist = pkg_resources.Distribution.from_location(None, file)
    name = dist.project_name
    return (name, file[len(name)+1:])

def file_to_package(file, basedir=None):
    """ Returns the package name for a given file.

        >>> file_to_package("foo-1.2.3_rc1.tar.gz")
        ('foo', '1.2.3-rc1.tar.gz')
        >>> file_to_package("foo-bar-1.2.tgz")
        ('foo-bar', '1.2.tgz')
        >>> """
    if os.path.splitext(file)[1].lower() == ".egg":
        return egg_to_package(file)
    split = file.rsplit("-", 1)
    if len(split) != 2:
        msg = "unexpected file name: %r " %(file, )
        msg += "(not in 'pkg-name-version.xxx' format"
        if basedir:
            msg += "; found in directory: %r" %(basedir)
        msg += ")"
        raise ValueError(msg)
    return (split[0], pkg_resources.safe_name(split[1]))


def archive_pip_packages(path, package_cmds):
    print '- Downloading pip packages'
    use_pip_main = False
    try:
        import pip
        pip_dist = pkg_resources.get_distribution('pip')
        version = pip_dist.version

        if version < '1.1':
            raise RuntimeError('pip >= 1.1 required, %s installed' % version)

        use_pip_main = True
    except ImportError:
        print '\n===\nWARNING:\nCannot import `pip` - falling back to using the pip executable.'
        print '(This will be deprecated in a future release.)\n===\n'

    if use_pip_main:
        cmds = ['install', '-d', path]
        cmds.extend(package_cmds)
        pip.main(cmds)
    else:
        check_call(["pip", "install", "-d", path] + package_cmds)


def get_md5_for_package(package):
    '''
    Calculate the md5 hash for a file
    at path `package` in a memory
    efficient way
    '''
    m = hashlib.md5()
    f = open(package, 'rb')
    read_size = 65536
    
    buf = f.read(read_size)
    while len(buf) > 0:
        m.update(buf)
        buf = f.read(read_size)

    f.close()
    return m.hexdigest()


def move_packages_to_source_tree(package_dir):
    '''
    Move any existing packages in to the
    appropriate directory structure
    Should be:
    packages/source/<PackageFirstLetterUppercase>/<PackageName>/*.gz|bz2
    '''
    print '- Moving packages to Simple source structure'
    source_dir = os.path.join(package_dir, 'packages', 'source')
    all_packages = glob.glob(os.path.join(package_dir, '*.gz'))
    all_packages.extend(glob.glob(os.path.join(package_dir, '*.bz2')))

    for package in all_packages:
        file_name = package.split('/')[-1]
        pkg_name, pkg_rest = file_to_package(file_name)
        pkg_move_path = os.path.join(source_dir, pkg_name[0].upper(), pkg_name)
        if not os.path.exists(pkg_move_path):
            os.makedirs(pkg_move_path)

        destination = os.path.join(pkg_move_path, file_name)
        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(package, destination)


def all_files_below_path(path):
    '''
    Helper function to walk a path
    tree and finds all the files
    '''
    for path, dirs, files in os.walk(path):
        for f in files:
            yield os.path.join(path, f)


def recreate_simple_index(package_dir):
    '''
    Simple - crawl the packages directory,
    recreating index files and the main index file,
    for all existing packages
    '''
    simple_index_file = os.path.join(package_dir, 'simple/index.html')
    print '- Creating Simple index at %s' % '/'.join(simple_index_file.split('/')[-2:])
    simple_path = os.path.join(package_dir, 'simple')
    shutil.rmtree(simple_path, ignore_errors=True)
    os.makedirs(simple_path)
    
    simple_index = '''
        <html>
            <head>
                <title>Simple Index</title>"
                 <meta name='api-version' value='2' />
            </head>
            <body>
    '''

    # Get a unique set of paths in the source tree
    source_dir = os.path.join(package_dir, 'packages', 'source')
    source_paths = [os.path.dirname(f)
        for f in all_files_below_path(source_dir)
            if f.endswith('.gz')
            or f.endswith('.bz2')]
    unique_paths = [path for path in sorted(set(source_paths))]
    
    # For each unique packages/source/<P>/<PackageName>/ folder
    for path in unique_paths:
        versions = glob.glob(os.path.join(path, '*.gz'))
        versions.extend(glob.glob(os.path.join(path, '*.bz2')))
        
        package_name = path.split('/')[-1]
        
        package_path = os.path.join(simple_path, package_name)
        os.makedirs(package_path)
        package_name_html = cgi.escape(package_name)
        simple_index += "<a href='{0}/'>{0}</a><br />\n".format(package_name_html)

        with open(os.path.join(package_path, "index.html"), "a") as f:
            f.write('''
                <html>
                    <head>
                        <title>Links for %s</title>
                    </head>
                    <body>
                        <h1>Links for %s</h1>
                    ''' % (package_name, package_name))
    
            # Write out each version of the package found in the directory
            for version in versions:
                md5 = get_md5_for_package(version)
                file_name = version.split('/')[-1]
                file_name_html = cgi.escape(file_name)
                file_relative_path = os.path.join('../../packages/source', '/'.join(version.split('/')[-3:]))
                f.write('''
                    <a href="%s#md5=%s">%s</a><br />
                ''' % (file_relative_path, md5, file_name_html))
            f.write('</body></html>\n')

    # Close the simple index html
    # and write it to a file
    simple_index += '</body></html>\n'
    with open(simple_index_file, 'w') as f:
        f.write(simple_index)



def dir2pi(argv=sys.argv):
    if len(argv) != 2:
        print(dedent("""
            usage: dir2pi PACKAGE_DIR

            Creates the directory PACKAGE_DIR/simple/ and populates it with the
            directory structure required to use with pip's --index-url.

            Assumes that PACKAGE_DIR contains a bunch of archives named
            'package-name-version.ext' (ex 'foo-2.1.tar.gz' or
            'foo-bar-1.3rc1.bz2').

            This makes the most sense if PACKAGE_DIR is somewhere inside a
            webserver's inside htdocs directory.

            For example:

                $ ls packages/
                foo-1.2.tar.gz
                $ dir2pi packages/
                $ find packages/
                packages/
                packages/source/
                packages/source/F/
                packages/source/F/foo/
                packages/source/F/foo/foo-1.2.tar.gz
                packages/simple/
                packages/simple/foo/
                packages/simple/foo/index.html
        """))
        return 1

    # Get the package dir
    package_dir = argv[1]
    if not os.path.isdir(package_dir):
        raise ValueError("no such directory: %r" % (package_dir, ))

    move_packages_to_source_tree(package_dir)
    recreate_simple_index(package_dir)
    
    return 0


@maintain_cwd
def pip2tgz(argv=sys.argv):
    if len(argv) < 3:
        print(dedent("""
            usage: pip2tgz OUTPUT_DIRECTORY PACKAGE_NAME ...

            Where PACKAGE_NAMES are any names accepted by pip (ex, `foo`,
            `foo==1.2`, `-r requirements.txt`).

            pip2tgz will download all packages required to install PACKAGE_NAMES and
            save them to sanely-named tarballs in OUTPUT_DIRECTORY.

            For example:

                $ pip2tgz /var/www/packages/ -r requirements.txt foo==1.2 baz/
        """))
        return 1

    outdir = os.path.abspath(argv[1])
    if not os.path.exists(outdir):
        os.mkdir(outdir)

    archive_pip_packages(outdir, argv[2:])
    os.chdir(outdir)
    num_pakages = len(glob.glob('./*.tar.*'))

    print('- %s packages downloaded' % num_pakages)
    return 0


def upload_to_s3(s3_path, working_dir):
    '''
    Uploads the contents of the working dir to s3
    '''
    try:
        import boto
        from boto.s3.key import Key
    except:
        print 'Exception importing boto, not uploading'
        return

    # First parse out the parts
    interesting_bits = s3_path.split('@')

    keys = interesting_bits[0].split(':')
    aws_access_key = keys[0]
    aws_secret_access_key = keys[1]

    path_info = interesting_bits[1].split('/')
    bucket = path_info[0]
    initial_path = '/'.join(path_info[1:])

    s3_conn = boto.connect_s3(aws_access_key, aws_secret_access_key)
    bucket = s3_conn.get_bucket(bucket)

    all_files = all_files_below_path(working_dir)
    for f in all_files:
        relative_path = f.replace(working_dir, '')
        if relative_path.startswith('/'):
            relative_path = relative_path[1:]
        s3path = os.path.join(initial_path, relative_path)
        print('  %s' % s3path)

        # Upload
        try:
            k = Key(bucket)
            k.key = s3path
            k.set_contents_from_filename(f, replace=True)
            k.set_acl('public-read')
        except Exception as ex:
            print('*** There was an exception ***\n%' % ex)
            return


def pip2pi(argv=sys.argv):
    if len(argv) < 3:
        print(dedent("""
            usage: pip2pi TARGET PACKAGE_NAME ...

            Combines pip2tgz and dir2pi, adding PACKAGE_NAME to package index
            TARGET.

            If TARGET contains ':' it will be treated as a remote path. The
            package index will be built locally then rsync will be used to copy
            it to the remote host.

            For example, to create a remote index:

                $ pip2pi example.com:/var/www/packages/ -r requirements.txt

            Or to create a local index:

                $ pip2pi ~/Sites/packages/ foo==1.2
        """))
        return 1

    target = argv[1]
    pip_packages = argv[2:]
    if "://" in target:
        is_remote = True
        working_dir = tempfile.mkdtemp(prefix="pip2pi-working-dir")
        atexit.register(lambda: shutil.rmtree(working_dir))
    else:
        is_remote = False
        working_dir = os.path.abspath(target)

    res = pip2tgz([argv[0], working_dir] + pip_packages)
    if res:
        print("pip2tgz returned an error; aborting.")
        return res

    res = dir2pi([argv[0], working_dir])
    if res:
        print("dir2pi returned an error; aborting.")
        return res

    if is_remote:
        parts == target.split('://')
        schema = parts[0]
        if schema.lower() == 's3':
            print('- Uploading to S3...')
            upload_to_s3(parts[1], working_dir)
        elif schema == 'rsync':
            target = parts[1]
            print('- Copying temporary index at %r to %r...' % (working_dir, target))
            check_call([
                "rsync",
                "--recursive", "--progress", "--links",
                working_dir + "/", target + "/",
            ])
        else:
            print('Schema "%s" unsupported at this time. Aborting.' % schema)
    return 0

import os
import sys
import cgi
import shutil
import atexit
import zipfile
import tempfile
import textwrap
import functools
from subprocess import check_call
import pkg_resources
import glob

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
                packages/foo-1.2.tar.gz
                packages/simple/
                packages/simple/foo/
                packages/simple/foo/index.html
                packages/simple/foo/foo-1.2.tar.gz
        """))
        return 1


    package_dir_path = lambda *x: os.path.join(package_dir, *x)

    # Get the package dir
    package_dir = argv[1]
    if not os.path.isdir(package_dir):
        raise ValueError("no such directory: %r" % (package_dir, ))

    # Move any existing packages in to the appropriate directory structure
    # Should be packages/source/<PackageFirstLetterUppercase>/<PackageName>/*.tar.*
    source_dir = package_dir_path('packages', 'source')
    all_packages = glob.glob(package_dir_path('*.tar.*'))  # .gz or .bz2
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
    
    # Simple - crawl the packages directory, recreating index files
    # and the main index file, for all existing packages
    simple_path = package_dir_path("simple")
    shutil.rmtree(simple_path, ignore_errors=True)
    os.makedirs(simple_path)
    simple_package_index = ("<html><head><title>Simple Index</title>"
                 "<meta name='api-version' value='2' /></head><body>\n")

    # Helper function to walk a directory tree and finds all the files
    def _all_files(directory):
        for path, dirs, files in os.walk(directory):
            for f in files:
                yield os.path.join(path, f)

    source_paths = [os.path.dirname(f)
        for f in _all_files(source_dir)
            if f.endswith('.tar.gz')
            or f.endswith('.tar.bz2')]
    unique_source_paths = [f for f in sorted(set(source_paths))]
    
    # For each unique packages/source/<P>/<PackageName>/ folder
    for path in unique_source_paths:
        package_versions = glob.glob(os.path.join(path, '*.tar.*'))
        package_name = path.split('/')[-1]
        
        simple_package_path = os.path.join(simple_path, package_name)
        os.makedirs(simple_package_path)
        package_name_html = cgi.escape(package_name)
        package_path_html = os.path.join(simple_path, package_name)
        simple_package_index += "<a href='{0}/'>{1}</a><br />\n".format(package_path_html, package_name_html)

        with open(os.path.join(simple_package_path, "index.html"), "a") as fp:
            fp.write('<html><head><title>Links for %s</title></head><body><h1>Links for %s</h1>\n' % (package_name, package_name))
    
            # Write out each version of the package found in the directory
            for version in package_versions:
                print version
                file_name = version.split('/')[-1]
                file_name_html = cgi.escape(file_name)
                file_relative_path = os.path.join('../../packages/source', '/'.join(version.split('/')[-3:]))
                fp.write('<a href="%s">%s</a><br />\n' % (file_relative_path, file_name_html))
            fp.write('</body></html>\n')

    # Close the simple index html file
    simple_package_index += "</body></html>\n"
    with open(package_dir_path("simple/index.html"), "w") as fp:
        fp.write(simple_package_index)
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
    
    check_call(["pip", "install", "-d", outdir] + argv[2:])
    os.chdir(outdir)
    num_pakages = len(glob.glob('./*.tar.gz'))

    print("%s .tar.gz saved to %r" %(num_pakages, argv[1]))
    return 0

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
    if ":" in target:
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
        print("copying temporary index at %r to %r..." %(working_dir, target))
        check_call([
            "rsync",
            "--recursive", "--progress", "--links",
            working_dir + "/", target + "/",
        ])
    return 0

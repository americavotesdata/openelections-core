import glob
import os.path
import posixpath

from blinker import signal
import github3

from openelex import COUNTRY_DIR

RAW_PREFIX = 'raw'
CLEAN_PREFIX = 'clean'

class ResultFileFinder(object):
    """Discover result files"""

    @classmethod
    def results_dir(cls):
        """
        Retrieve the path where result files are located.

        Returns:
            String containing the path to the directory containing result files.
        """
        return os.path.join(COUNTRY_DIR, 'bakery')

    @classmethod
    def get_filenames(cls, state, datefilter=None, raw=False,
            search_dir=None):
        """
        Retrieve results filenames based on filters.

        Args:
            state: Two-letter state-abbreviation, e.g. NY
            datefilter: Portion of a YYYYMMDD date, e.g. YYYY, YYYYMM, etc.
                Result files will only be published if the date portion of the
                filename matches the date string. Default is to publish all result
                files for the specified state.
            raw: Search for raw result files.  Default is to search for 
                cleaned/standardized result files.
            search_dir: Directory to search for files.  Default is the
                return value of the ``results_dir()`` method.

        Returns:
            A list of strings containing paths to result files matching
            the specified filters.
            
        """
        filenames = []
        extensions = (".csv", ".json")

        if search_dir is None:
            search_dir = cls.results_dir()

        for ext in extensions: 
            glob_s = cls.build_glob(state, ext=ext, search_dir=search_dir,
                datefilter=datefilter, raw=raw)
            filenames.extend(glob.glob(glob_s))

        return filenames

    @classmethod
    def build_glob(cls, state, search_dir, ext, datefilter=None, raw=False):
        """
        Retrieve a path name string to pass to glob.glob() 

        Args:
            state: Two-letter state-abbreviation, e.g. NY
            datefilter: Portion of a YYYYMMDD date, e.g. YYYY, YYYYMM, etc.
                Return value will only match results if the date portion of the
                filename matches the date string. Default is to match all 
                result files for the specified state.
            raw: Match raw result files.  Default is to match
                cleaned/standardized result files.
            ext: Filename extension of result files, including leading '.'.
                For example, ".csv".
            search_dir: Directory containing result files.  

        Returns:
            A list of strings containing paths to result files matching
            the specified filters.
            
        """
        filename_bits = []

        if datefilter:
            datefilter_bit = datefilter
            if len(datefilter_bit) < 6:
                datefilter_bit += "*"
        else:
            datefilter_bit = "*"
        filename_bits.append(datefilter_bit)

        filename_bits.append(state)
        filename_bits.append('*')

        if raw:
            filename_bits.append(RAW_PREFIX)

        filename_glob = "{}".format("__".join(filename_bits)) + ext 
        pathname = os.path.join(search_dir, filename_glob)

        return pathname


class BasePublisher(object):
    """
    Publishes result files to a remote location
    """
    @classmethod
    def get_filenames(cls, state, datefilter=None, raw=False,
            search_dir=None):
        return ResultFileFinder.get_filenames(state=state, datefilter=datefilter,
            raw=raw, search_dir=search_dir)

    def publish(self, state, datefilter=None, raw=False):
        """
        Publish baked result files
        
        Args:
            state: Two-letter state-abbreviation, e.g. NY
            datefilter: Portion of a YYYYMMDD date, e.g. YYYY, YYYYMM, etc.
                Result files will only be published if the date portion of the
                filename matches the date string. Default is to publish all result
                files for the specified state.
            raw: Publish raw result files.  Default is to publish
                cleaned/standardized result files.
            
        """
        raise NotImplemented("You must implement this method in a subclass")


class GitHubPublisher(BasePublisher):
    """
    Publisher that pushes files to GitHub pages
    """

    def __init__(self, username, password):
        self._username = username
        self._password = password

    @classmethod
    def results_repo_name(cls, state):
        """
        Get the GitHub repository name for a state's results rep.

        Args:
            state: Two-letter state-abbreviation, e.g. NY

        Returns:
            String containing the name of the results repository.

        """
        return "openelections-results-{}".format(state.lower())
        
    def publish(self, state, datefilter=None, raw=False):
        gh = github3.login(self._username, self._password)
        repo = gh.repository("openelections", self.results_repo_name(state))
        for filename in self.get_filenames(state, datefilter, raw):
            self.publish_file(repo, filename)
        # Merge 'master' branch into 'gh-pages'
        repo.merge('gh-pages', 'master')

    def get_path(self, filename):
        """
        Get the path within a repository for a file.

        Args:
            filename (string): Local filename of a results file.

        Returns:
            String containing path within the repository of the resutls file.
            
        """
        base, ext = os.path.splitext(filename)
        without_dir = os.path.basename(filename)
        if base.endswith("raw"):
            return posixpath.join(RAW_PREFIX, without_dir)
        else:
            return posixpath.join(CLEAN_PREFIX, without_dir)

    def publish_file(self, repo, filename, branch='master'):
        """
        Publish a single file to GitHub.

        Args:
            repo (github3.repos.repo.Repository): Repository object for the
                GitHub repository that contains the state's files.
            filename (string): Local filename of results file to be published.
            branch (string): Name of git branch where the files will be
                published.
        """
        pre_publish = signal('pre_publish')
        post_publish = signal('post_publish')
        pre_publish.send(self.__class__, filename=filename)
        path = self.get_path(filename)
        with open(filename, 'r') as f:
            content = f.read()
            sha = self.get_sha(repo, path, branch)
            if sha:
                # Update file
                msg = "Update file {}".format(path)
                result = repo.update_file(path, msg, content, sha)
            else:
                # Create file
                msg = "Create file {}".format(path)
                result = repo.create_file(path, msg, content)

        post_publish.send(self.__class__, filename=filename)

    def get_sha(self, repo, path, branch):
        """
        Get the sha for a file in a GitHub repo.

        Arguments:
            repo (github3.repos.repo.Repository): Repository object for the
                GitHub repository that contains the file.
            path (string): path within the repository of the resutls file.

        Returns:
            String containing sha for the file or None if the file does not
            exist in the repo.

        """
        tree = repo.tree(branch).recurse()
        for hsh in tree.tree:
            if hsh.path == path:
                return hsh.sha
        else:
            return None
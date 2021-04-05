# Copyright: Daveight and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
"""
Test Runner API
"""

import json
import numbers
import os
import signal
import subprocess
import sys
import tempfile
import re
from abc import abstractmethod, ABC
from json import JSONDecodeError
from os.path import normpath
from threading import Thread
from typing import List, Optional
from queue import Queue

from deepdiff import DeepDiff

from testing.framework.test_suite_gen import START_USER_SRC_MARKER
from testing.framework.types import SrcFile, TestResponse
from testing.framework.console_logger import ConsoleLogger, TestLogger

isMac = sys.platform.startswith("darwin")
isWin = sys.platform.startswith("win32")
isLin = not isMac and not isWin


def create_src_file(src: str, name: str) -> SrcFile:
    """
    Stores the source code provided into temporary file
    :param src: target source code
    :param name: name of the file
    :return: Tuple - the file's parent dir and the target file
    """
    workdir = tempfile.TemporaryDirectory()
    src_file = open(os.path.join(workdir.name, name), 'w')
    src_file.write(src)
    src_file.close()
    return SrcFile(src, src_file, workdir)


def get_resource_path():
    """
    Returns the Resource's base path, depending on the current OS
    :return: the path of the Resources folder in the system
    """
    result = '/opt/dev/dave8/anki/testing'
    # if isWin:
    #     result = sys._MEIPASS
    # elif isMac:
    #     result = os.environ['RESOURCEPATH']
    # else:
    #     raise Exception('not supported OS')
    return '"' + result + '"'


def are_same_numbers(arg1, arg2):
    """
    Checks if both arguments are of numerical type and the delta between them is less than 1e-4
    :param arg1: first arg
    :param arg2: second arg
    :return: True - args both numbers and their values are equal, False - otherwise
    """
    if isinstance(arg1, numbers.Number) and isinstance(arg2, numbers.Number):
        if abs(arg1 - arg2) < 0.0001:
            return True


def compare(obj1, obj2) -> bool:
    """
    Performs deep difference between two objects
    :return True - if objects are equal, False otherwise
    """
    return DeepDiff(obj1, obj2, ignore_order=True, significant_digits=4) == {}


def get_code_offset(src: str, user_src_start_marker: str) -> int:
    """
    Returns number of lines which precede solution src
    :param src: solution src
    :param user_src_start_marker: begin of solution src marker
    """
    start_src_index = src.index(user_src_start_marker)
    return len(src[:start_src_index].split('\n'))


class TestRunner(ABC):
    """
    Base class for language specific test suite runners:
        -submits tests for execution
        -performs error handling
        -parses a test's results and compares them with expected value
    """

    def __init__(self):
        self.pid = None
        self.stopped = False

    def enqueue_output(self, out, queue):
        for line in iter(out.readline, b''):
            if self.stopped:
                break
            queue.put(line)
        print('closing!')
        out.close()

    def run(self, src_code: str, test_cases: List[str], logger: ConsoleLogger):
        """
        Submits a source code for execution
        :param src_code: source code to run
        :param test_cases: text rows containing a testing data
        :param logger: console logger
        """
        if self.pid is not None:
            raise Exception('Another test is already running ' + str(self.pid))

        resource_path = get_resource_path()
        src_file = create_src_file(src_code, self.get_src_file_name())
        test_logger = logger.get_testing_logger(len(test_cases) - 1)
        self.stopped = False

        compile_cmd = self.get_compile_cmd(src_file, resource_path, False)
        if compile_cmd is not None:
            logger.info('Compiling...')
            proc = subprocess.Popen(compile_cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            self.pid = proc.pid
            stdout, stderr = proc.communicate()
            if self.check_for_errors(stderr, src_file, logger):
                self.kill()
                return

        logger.info('Running tests...<br/>')
        run_cmd = self.get_run_cmd(src_file, resource_path, False)
        run_cmd = normpath(run_cmd)

        ON_POSIX = 'posix' in sys.builtin_module_names

        try:
            proc = subprocess.Popen(run_cmd, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1, close_fds=ON_POSIX)
            stdout_q = Queue()
            stdout_t = Thread(target=self.enqueue_output, args=(proc.stdout, stdout_q))
            stdout_t.daemon = True
            stdout_t.start()

            stderr_q = Queue()
            stderr_t = Thread(target=self.enqueue_output, args=(proc.stderr, stderr_q))
            stderr_t.daemon = True
            stderr_t.start()

            self.pid = proc.pid

            for idx, tc in enumerate(test_cases[1:], start=1):
                if proc.poll() is not None:
                    break
                splt = re.split('(?<!\\\\);', tc)
                expected_val = json.loads(splt[-1])
                args = '[' + ','.join(splt[:-1]) + ']'

                proc.stdin.write(args + '\r\n')
                proc.stdin.flush()
                tst_resp: Optional[TestResponse] = None
                error = ''
                while tst_resp is None and not self.stopped:
                    while not stderr_q.empty():
                        error += stderr_q.get_nowait()
                    if error and self.check_for_errors(error, src_file, logger):
                        return
                    if stdout_q.empty():
                        continue
                    line = stdout_q.get_nowait()
                    if len(line) > 0:
                        try:
                            tst_resp = json.loads(line, object_hook=lambda d: TestResponse(**d))
                        except JSONDecodeError:
                            pass
                        if not tst_resp or (tst_resp.result is None and tst_resp.duration is None):
                            logger.info(line)
                        else:
                            break
                if self.stopped:
                    test_logger.cancel()
                    return
                assert tst_resp is not None
                if compare(tst_resp.result, expected_val):
                    test_logger.passed(idx, tst_resp.duration)
                else:
                    test_logger.fail(idx, args, expected_val, tst_resp.result)
                    return
            if self.stopped:
                test_logger.cancel()
            else:
                test_logger.log('<br/>All tests <span class="passed">PASSED</span><br/><br/>')
        finally:
            self.kill()

    @abstractmethod
    def get_src_file_name(self) -> str:
        """
        Name of a file to be executed
        """
        pass

    @abstractmethod
    def get_run_cmd(self, src_file: SrcFile, resource_path: str, is_win: bool) -> str:
        """
        test's run command
        :param src_file: tatget file to be executed
        :param resource_path: path containing resource files
        :param is_win: platform is windows if true (unix/osx if false)
        """
        pass

    @abstractmethod
    def get_compile_cmd(self, src_file: SrcFile, resource_path: str, is_win: bool) -> str:
        """
        test's compile command
        :param src_file: tatget file to be executed
        :param resource_path: path containing resource files
        :param is_win: platform is windows if true (unix/osx if false)
        """
        pass

    @abstractmethod
    def get_error_message(self, error: str, file_name: str, code_offset: int) -> str:
        """
        Contains logic of parsing stderr, to distinguish between errors and warnings
        and pre-process error messages (setting correct line number, strip file name, etc...)
        :param error: target error message from compiler or interpreter
        :param file_name: a test's file name
        :param code_offset: line offset used to calculate correct line number of an error
        """
        pass

    def check_for_errors(self, error, src_file: SrcFile, logger: ConsoleLogger) -> bool:
        """
        Checks if there are error messages in stderr, if there are errors - logs them to the console
        :param error: target error stream
        :param src_file: target source file
        :param logger: console logger
        :return: true/false - has errors or not
        """
        if not error:
            return False
        offset = get_code_offset(src_file.text, START_USER_SRC_MARKER)
        error_msg = self.get_error_message(error, src_file.file.name, offset)
        if error_msg:
            error_msg = re.sub('\n+', '<br>', error_msg)
            logger.error(error_msg)
            return True
        return False

    def read_test_results(self, output, test_logger: TestLogger) -> bool:
        """
        Reads stdout, every line is decoded to json and compared with the expected result
        if results not match, test is execution is stopped
        :param output: test stdout
        :param test_logger: console logger
        :return: True all test cases passed successfully, False otherwise
        """
        for i, line in enumerate(output, start=1):
            if self.stopped:
                return True
            try:
                tc = json.loads(line)
            except JSONDecodeError:
                return False
            if compare(tc['expected'], tc['result']):
                test_logger.passed(i, tc['duration'])
            else:
                test_logger.fail(i, tc['args'], tc['expected'], tc['result'])
                return False
        return True

    def kill(self):
        """
        Stop currently executing processes
        """
        if self.pid is not None:
            try:
                self.stopped = True
                os.kill(self.pid, signal.SIGKILL)
            except:
                pass
            finally:
                self.pid = None

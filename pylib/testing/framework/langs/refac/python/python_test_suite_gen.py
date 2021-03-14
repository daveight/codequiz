from testing.framework.langs.refac.python.python_input_converter import PythonInputConverter
from testing.framework.langs.refac.test_suite_gen import TestSuiteGenerator, TestSuiteConverters
from testing.framework.langs.refac.types import TestSuite
from testing.framework.langs.refac.string_utils import render_template
from testing.framework.syntax.syntax_tree import SyntaxTree


class PythonTestSuiteGenerator(TestSuiteGenerator):
    def __init__(self):
        super().__init__(line_comment_char='#', converters={'input': PythonInputConverter()})

    def _get_imports(self):
        return 'import datetime\nimport json'

    def _get_testing_src(self, ts: TestSuite, converters: TestSuiteConverters, solution_src: str):
        return solution_src + render_template('''
            {% for converter in converters %}
            def {{converter.fn_name}}({{converter.arg_name}}) -> {{converter.ret_type}}:
            {{converter.src}}
            {% endfor %}
            index = 0
            file = open('{{ts.test_cases_file}}')
            lines = file.readlines()
            for line in lines:
            \tvalues = []
            \tcols = line.split(';')
            \tfor i, col in enumerate(cols):
            \t\tvalues.append(json.loads(col))
            \targs = []
            {% for c in converters.input_args %}
            \targs.append({{c.fn_name}}(values[{{loop.index0}}]))
            {% endfor %}
            \tstart = datetime.datetime.now()
            \tresult = {{ts.fn_name}}(*args)
            \tend = datetime.datetime.now()
            \ttime_diff = (end - start)
            \tduration = (time_diff.days * 86400000) + (time_diff.seconds * 1000) + (time_diff.microseconds / 1000)
            \tprint(json.dumps({'expected': values[len(values) - 1],
            \t\t'result': result,
            \t\t'args': args,
            \t\t'duration': duration }, default=lambda obj: obj.__dict__))
            ''', ts=ts, solution_src=solution_src, converters=converters, retab=True)
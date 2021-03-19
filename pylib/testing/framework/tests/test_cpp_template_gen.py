import unittest

from testing.framework.dto.test_arg import TestArg
from testing.framework.dto.test_suite import TestSuite
from testing.framework.langs.cpp.cpp_template_gen import CppTemplateGenerator


class CppTemplateGenTests(unittest.TestCase):

    def test_sum_template(self):
        test_suite = TestSuite('sum')
        test_suite.test_args = [TestArg('TypeA', 'a')]
        test_suite.description = 'calc sum'
        test_suite.result_type = 'int'
        test_suite.user_types = {}
        generator = CppTemplateGenerator()
        result = generator.generate_solution_template(test_suite)
        self.assertEqual('''/**
* calc sum
*/

class Solution {
public:
    int sum(TypeA a) {
        //Add code here
    }
};''', result)

    def test_sum_template_with_user_type(self):
        test_suite = TestSuite('sum')
        test_suite.test_args = [TestArg('TypeA', 'a')]
        test_suite.description = 'calc sum'
        test_suite.result_type = 'int'
        test_suite.classes = {'TypeA': '''struct TypeA {
\tint a;
}'''}
        generator = CppTemplateGenerator()
        result = generator.generate_solution_template(test_suite)
        self.assertEqual('''/**
* calc sum
*/
struct TypeA {
    int a;
}
class Solution {
public:
    int sum(TypeA a) {
        //Add code here
    }
};''', result)
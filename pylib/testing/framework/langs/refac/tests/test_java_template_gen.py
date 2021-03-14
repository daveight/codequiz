import textwrap
import unittest

from testing.framework.langs.refac.java.java_template_gen import JavaTemplateGenerator
from testing.framework.langs.refac.types import TestSuite
from testing.framework.syntax.syntax_tree import SyntaxTree


class JavaTemplateGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = JavaTemplateGenerator()

    def test_simple_template_generation(self):
        ts = TestSuite()
        ts.fn_name = 'sum'
        ts.description = 'calculate sum of 2 numbers'
        tree = SyntaxTree.of(['int[a]', 'int[b]', 'int'])
        self.assertEqual(textwrap.dedent('''
            /**
            * calculate sum of 2 numbers 
            */
            public class Solution {
                public int sum(int a, int b) {
                    //Add code here
                }
            }
            ''').lstrip(), self.generator.get_template(tree, ts))

    def test_solution_with_custom_types_generation(self):
        ts = TestSuite()
        ts.fn_name = 'sum'
        ts.description = 'calculate sum of 2 objects'
        tree = SyntaxTree.of(['object(int[val])<TypeA>[a]', 'object(int[val])<TypeB>[b]', 'int'])
        self.assertEqual(textwrap.dedent('''
            /**
            * calculate sum of 2 objects 
            */
            public class Solution {
                public static class TypeA {
                    int val;
                }

                public static class TypeB {
                    int val;
                }

                public int sum(TypeA a, TypeB b) {
                    //Add code here
                }
            }
            ''').lstrip(), self.generator.get_template(tree, ts))

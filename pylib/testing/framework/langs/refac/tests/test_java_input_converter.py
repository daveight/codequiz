import textwrap
import unittest

from testing.framework.langs.refac.java.java_input_converter import JavaInputConverter
from testing.framework.langs.refac.types import ConverterFn
from testing.framework.syntax.syntax_tree import SyntaxTree


class JavaInputConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.converter = JavaInputConverter()
        ConverterFn.reset_counter()

    def test_array_of_arrays_of_ints(self):
        tree = SyntaxTree.of(['array(array(int))[a]'])
        _, converters = self.converter.get_converters(tree)
        self.assertEqual(3, len(converters))
        self.assertEqual(ConverterFn('', '''return value.asInt();''', 'JsonNode', 'int'), converters[0])
        self.assertEqual(ConverterFn('', textwrap.dedent('''
            int result[] = int[value.size()];
            int i = 0;
            for (JsonNode node : value) {
                result[i++] = converter1(node);
            }
            return result;''').lstrip(), 'JsonNode', 'int[]'), converters[1])
        self.assertEqual(ConverterFn('a', textwrap.dedent('''
            int[] result[] = int[value.size()][];
            int i = 0;
            for (JsonNode node : value) {
                result[i++] = converter2(node);
            }
            return result;'''), 'JsonNode', 'int[][]'), converters[2])

    def test_object_conversion(self):
        tree = SyntaxTree.of(['object(int[a],int[b])<Edge>[a]'])
        _, converters = self.converter.get_converters(tree)
        self.assertEqual(3, len(converters))
        self.assertEqual(ConverterFn('a', '''return value.asInt();''', 'JsonNode', 'int'), converters[0])
        self.assertEqual(ConverterFn('b', '''return value.asInt();''', 'JsonNode', 'int'), converters[1])
        self.assertEqual(ConverterFn('a', '''
            Edge result = new Edge();
            result.a = converter1(val.get(0));
            result.b = converter2(val.get(1));

            return result;
        ''', 'JsonNode', 'Edge'), converters[2])

    def test_obj_nested_list(self):
        tree = SyntaxTree.of(['object(list(int)[a],int[b])<Edge>[a]'])
        arg_converters, converters = self.converter.get_converters(tree)
        self.assertEqual(1, len(arg_converters))
        self.assertEqual(4, len(converters))
        self.assertEqual(ConverterFn('', '''return value.asInt();''', 'JsonNode', 'Integer'), converters[0])
        self.assertEqual(ConverterFn('a', '''
            List<Integer> result = new ArrayList<>();
            for (JsonNode node : value) {
                result.add(converter1(node));
            }
            return result;'''.lstrip(), 'JsonNode', 'List<Integer>'), converters[1])
        self.assertEqual(ConverterFn('b', '''return value.asInt();''', 'JsonNode', 'int'), converters[2])
        self.assertEqual(ConverterFn('a', '''
            Edge result = new Edge();
            result.a = converter2(val.get(0));
            result.b = converter3(val.get(1));
            return result;
        ''', 'JsonNode', 'Edge'), converters[3])


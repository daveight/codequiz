import unittest

from testing.framework.langs.refac.cpp.cpp_output_converter import CppOutputConverter
from testing.framework.langs.refac.types import ConverterFn
from testing.framework.syntax.syntax_tree import SyntaxTree


class CppOutputConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.converter = CppOutputConverter()
        ConverterFn.reset_counter()

    def test_array_of_arrays_of_ints(self):
        tree = SyntaxTree.of(['array(array(int))[a]'])
        _, converters = self.converter.get_converters(tree)
        self.assertEqual(3, len(converters))
        self.assertEqual(ConverterFn('', '''
            jute::jValue result;
            result.set_type(jute::JNUMBER);
            result.set_string(std::to_string(value));
            return result;
        ''', 'int', 'jute::jValue'), converters[0])
        self.assertEqual(ConverterFn('', '''
            jute::jValue result; 
            result.set_type(jute::JARRAY);
            for (int i = 0; i < value.size(); i++) {
                result.add_element((value[i]));
            }
            return result;'''.lstrip(), 'vector<int>', 'jute::jValue'), converters[1])
        self.assertEqual(ConverterFn('a', '''
            jute::jValue result; 
            result.set_type(jute::JARRAY);
            for (int i = 0; i < value.size(); i++) {
                result.add_element((value[i]));
            }
            return result;'''.lstrip(), 'vector<vector<int>>', 'jute::jValue'), converters[2])

    def test_object_conversion(self):
        tree = SyntaxTree.of(['object(int[a],int[b])<Edge>[a]'])
        _, converters = self.converter.get_converters(tree)
        self.assertEqual(3, len(converters))
        self.assertEqual(ConverterFn('a', '''
            jute::jValue result;
            result.set_type(jute::JNUMBER);
            result.set_string(std::to_string(value));
            return result;
        ''', 'int', 'jute::jValue'), converters[0])
        self.assertEqual(ConverterFn('b', '''
            jute::jValue result;
            result.set_type(jute::JNUMBER);
            result.set_string(std::to_string(value));
            return result;
        ''', 'int', 'jute::jValue'), converters[1])
        self.assertEqual(ConverterFn('a', '''
            jute::jValue result;
            result.set_type(jute::JOBJECT);
            jute::jValue prop;
            prop = converter1(value[0]);
            result.add_property("a", prop);
            prop = converter2(value[1]);
            result.add_property("b", prop);
            return result;
        ''', 'Edge', 'jute::jValue'), converters[2])

    def test_obj_nested_list(self):
        tree = SyntaxTree.of(['object(list(int)[a],int[b])<Edge>[a]'])
        arg_converters, converters = self.converter.get_converters(tree)
        self.assertEqual(1, len(arg_converters))
        self.assertEqual(4, len(converters))
        self.assertEqual(ConverterFn('', '''
            jute::jValue result;
            result.set_type(jute::JNUMBER);
            result.set_string(std::to_string(value));
            return result;'''.lstrip(), 'int', 'jute::jValue'), converters[0])
        self.assertEqual(ConverterFn('a', '''
            jute::jValue result; 
            result.set_type(jute::JARRAY);
            for (int i = 0; i < value.size(); i++) {
                result.add_element((value[i]));
            }
            return result;'''.lstrip(), 'vector<int>', 'jute::jValue'), converters[1])
        self.assertEqual(ConverterFn('b', '''
            jute::jValue result;
            result.set_type(jute::JNUMBER);
            result.set_string(std::to_string(value));
            return result;'''.lstrip(), 'int', 'jute::jValue'), converters[2])
        self.assertEqual(ConverterFn('a', '''
            jute::jValue result; 
            result.set_type(jute::JOBJECT);
            jute::jValue prop;
            prop = converter2(value[0]);
            result.add_property("a", prop);
            prop = converter3(value[1]);
            result.add_property("b", prop);
            return result;'''.lstrip(), 'Edge', 'jute::jValue'), converters[3])


from testing.framework.langs.refac.string_utils import render_template
from testing.framework.langs.refac.type_converter import TypeConverter
from testing.framework.langs.refac.types import ConverterFn
from testing.framework.syntax.syntax_tree import SyntaxTree, is_primitive_type


class JavaOutputConverter(TypeConverter):
    def visit_array(self, node: SyntaxTree, context):
        child = self.render(node.first_child(), context)
        return ConverterFn(node.name, 'return value;', child.ret_type + '[]', child.ret_type + '[]')

    def visit_list(self, node: SyntaxTree, context):
        child = self.render(node.first_child(), context)
        return ConverterFn(node.name, 'return value;', 'List<' + child.ret_type + '>', 'List<' + child.ret_type + '>')

    def visit_map(self, node: SyntaxTree, context):
        converters = [self.render(child, context) for child in node.nodes]
        src = render_template('''
            \tList result = new ArrayList();
            \tfor (Map.Entry<{{converters[0].arg_type}}, {{converters[1].arg_type}}> entry : value.entrySet()) {
            \t\tresult.add({{converters[0].fn_name}}(entry.getKey());
            \t\tresult.add({{converters[1].fn_name}}(entry.getValue());
            \t}
            return result;''', converters=converters)
        return ConverterFn(node.name, src, 'Map', 'List')

    def visit_int(self, node: SyntaxTree, context):
        t = 'int' if is_primitive_type(node) else 'Integer'
        return ConverterFn(node.name, 'return value;', t, t)

    def visit_long(self, node: SyntaxTree, context):
        t = 'long' if is_primitive_type(node) else 'Long'
        return ConverterFn(node.name, 'return value;', t, t)

    def visit_float(self, node: SyntaxTree, context):
        t = 'double' if is_primitive_type(node) else 'Double'
        return ConverterFn(node.name, 'return value;', t, t)

    def visit_string(self, node: SyntaxTree, context):
        return ConverterFn(node.name, 'return value;', 'String', 'String')

    def visit_bool(self, node: SyntaxTree, context):
        t = 'bool' if is_primitive_type(node) else 'Boolean'
        return ConverterFn(node.name, 'return value;', t, t)

    def visit_obj(self, node: SyntaxTree, context):
        converters = [self.render(child, context) for child in node.nodes]
        src = render_template('''
            \tList result = new ArrayList();
            {% for converter in converters %}
                \tresult.add({{converter.fn_name}}(value.{{converter.prop_name}}));
            {% endfor %}
            return result;''', converters=converters)
        return ConverterFn(node.name, src, node.node_type, 'List')
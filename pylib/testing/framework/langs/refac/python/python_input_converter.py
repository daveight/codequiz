from testing.framework.langs.refac.string_utils import render_template
from testing.framework.langs.refac.type_converter import TypeConverter
from testing.framework.langs.refac.types import ConverterFn
from testing.framework.syntax.syntax_tree import SyntaxTree


class PythonInputConverter(TypeConverter):
    def visit_array(self, node: SyntaxTree, context):
        return self.visit_list(node, context)

    def visit_list(self, node: SyntaxTree, context):
        child = self.render(node.first_child(), context)
        src = render_template('\treturn [{{fn}}(item) for item in value]', fn=child.fn_name)
        return ConverterFn(node.name, src, '', 'List[' + child.ret_type + ']')

    def visit_map(self, node: SyntaxTree, context):
        raise Exception('todo')

    def visit_int(self, node: SyntaxTree, context):
        return ConverterFn(node.name, '\treturn int(value)', '', 'int')

    def visit_long(self, node: SyntaxTree, context):
        self.visit_int(node, context)

    def visit_float(self, node: SyntaxTree, context):
        return ConverterFn(node.name, '\treturn float(value)', '', 'float')

    def visit_string(self, node: SyntaxTree, context):
        return ConverterFn(node.name, '\treturn str(value)', '', 'str')

    def visit_bool(self, node: SyntaxTree, context):
        return ConverterFn(node.name, '\treturn bool(value)', '', 'bool')

    def visit_obj(self, node: SyntaxTree, context):
        converters = [self.render(child, context) for child in node.nodes]
        src = render_template(
            '\t{{t}}({%for c in cs%}{{c.fn_name}}(value[{{loop.index0}}]){%if not loop.last%},{%endif%}{%endfor %})',
            cs=converters, t=node.node_type)
        return ConverterFn(node.name, src, 'List', node.node_type)

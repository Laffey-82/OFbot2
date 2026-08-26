from __future__ import annotations

import ast
import operator

from app.core.messages import Message, MessageEvent
from app.core.plugin import Plugin, PluginContext

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def _eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand)
    raise ValueError("unsupported expression")


class CalcPlugin(Plugin):
    def setup(self, ctx: PluginContext) -> None:
        @ctx.commands.command("calc", aliases={"计算"}, permission="calc.use", plugin_name=ctx.name)
        async def calc(event: MessageEvent, args: Message, command_ctx) -> None:
            expr = args.extract_plain_text().strip()
            if not expr:
                await event.reply("用法：/calc 1+2*3")
                return
            try:
                result = _eval(ast.parse(expr, mode="eval"))
                await event.reply(f"{expr} = {result}")
            except Exception:
                await event.reply("表达式无效")


def create_plugin() -> Plugin:
    return CalcPlugin()

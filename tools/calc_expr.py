"""计算题的表达式：自己遍历语法树，只认白名单写法，不用 eval / compile。

题库里的每一步写成「名 = 表达式」，比如 `pv = amt / (1 + rr) ** n`。能用的：
数字、参数名和前面算出的名字（小写字母开头）、正负号、+ - * / **、括号、
函数 min(a, b) max(a, b) abs(x) round(x, n) ln(x) log10(x) exp(x) sqrt(x) ncdf(x)（标准正态分布函数）、
求和 sum(表达式 for t in range(a, b))（一层、不带 if、最多 1000 项）。
别的一律拒收，错误都是一句中文（ExprError）。
"""
import ast
import math
import re

MAX_LEN = 300
MAX_NODES = 150
MAX_TERMS = 1000
MAX_EXP = 1000
BUDGET = 200000
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
STEP_RE = re.compile(r"^\s*([a-z][a-z0-9_]*)\s*=\s*(.+?)\s*$")
FUNCS = {"min": (2, min), "max": (2, max), "abs": (1, abs), "round": (2, lambda x, n: round(x, int(n))),
         "ln": (1, math.log), "log10": (1, math.log10), "exp": (1, math.exp), "sqrt": (1, math.sqrt),
         "ncdf": (1, lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2))))}  # 标准正态分布函数 N(x)
RESERVED = set(FUNCS) | {"sum", "range"}


class ExprError(ValueError):
    """表达式不合格或算不出来；消息是一句中文。"""


def _finite(x, expr):
    if not math.isfinite(x):
        raise ExprError(f"算出来不是有限的数（{expr}）")
    return x


def _pow(a, b, expr):
    if abs(b) > MAX_EXP:
        raise ExprError(f"指数太大（{expr}）")
    if a < 0 and not float(b).is_integer():
        raise ExprError(f"负数开非整数次方（{expr}）")
    if a == 0 and b < 0:
        raise ExprError(f"零的负数次方（{expr}）")
    try:
        return math.pow(a, b)
    except (OverflowError, ValueError):
        raise ExprError(f"幂算不出来（{expr}）") from None


class _Eval:
    def __init__(self, expr, env):
        self.expr, self.env, self.left = expr, env, BUDGET

    def tick(self):
        self.left -= 1
        if self.left < 0:
            raise ExprError(f"计算量太大（{self.expr}）")

    def run(self, node):
        self.tick()
        if isinstance(node, ast.Expression):
            return self.run(node.body)
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float):
                raise ExprError(f"只能写数字（{self.expr}）")
            return _finite(float(node.value), self.expr)
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise ExprError(f"不认识的名字 {node.id}（{self.expr}）")
            return self.env[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = self.run(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            return self.binop(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        raise ExprError(f"不支持的写法 {type(node).__name__}（{self.expr}）")

    def binop(self, node):
        a, b = self.run(node.left), self.run(node.right)
        op = node.op
        if isinstance(op, ast.Add):
            v = a + b
        elif isinstance(op, ast.Sub):
            v = a - b
        elif isinstance(op, ast.Mult):
            v = a * b
        elif isinstance(op, ast.Div):
            if b == 0:
                raise ExprError(f"除以零（{self.expr}）")
            v = a / b
        elif isinstance(op, ast.Pow):
            v = _pow(a, b, self.expr)
        else:
            raise ExprError(f"不支持的运算 {type(op).__name__}（{self.expr}）")
        return _finite(v, self.expr)

    def call(self, node):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise ExprError(f"函数只能直接写名字、不带关键字参数（{self.expr}）")
        name = node.func.id
        if name == "sum":
            return self.summation(node)
        if name not in FUNCS:
            raise ExprError(f"不认识的函数 {name}（{self.expr}）")
        n, fn = FUNCS[name]
        if len(node.args) != n:
            raise ExprError(f"{name} 要 {n} 个参数（{self.expr}）")
        args = [self.run(a) for a in node.args]
        try:
            return _finite(float(fn(*args)), self.expr)
        except (ValueError, OverflowError):
            raise ExprError(f"{name} 算不出来（{self.expr}）") from None

    def summation(self, node):
        gen = node.args[0] if len(node.args) == 1 else None
        if not isinstance(gen, ast.GeneratorExp) or len(gen.generators) != 1:
            raise ExprError(f"sum 只能写 sum(表达式 for t in range(a, b))（{self.expr}）")
        comp = gen.generators[0]
        it = comp.iter
        if (comp.ifs or comp.is_async or not isinstance(comp.target, ast.Name)
                or not isinstance(it, ast.Call) or not isinstance(it.func, ast.Name) or it.func.id != "range"
                or it.keywords or not 1 <= len(it.args) <= 2):
            raise ExprError(f"sum 只能写 sum(表达式 for t in range(a, b))（{self.expr}）")
        var = comp.target.id
        if not NAME_RE.match(var) or var in self.env or var in RESERVED:
            raise ExprError(f"求和变量 {var} 和已有名字重了（{self.expr}）")
        bounds = [self.run(a) for a in it.args]
        if not all(float(b).is_integer() for b in bounds):
            raise ExprError(f"range 的边界要是整数（{self.expr}）")
        lo, hi = (0, int(bounds[0])) if len(bounds) == 1 else (int(bounds[0]), int(bounds[1]))
        if hi - lo > MAX_TERMS:
            raise ExprError(f"求和项太多（最多 {MAX_TERMS}）（{self.expr}）")
        total = 0.0
        for t in range(lo, hi):
            self.env[var] = float(t)
            try:
                total += self.run(gen.elt)
            finally:
                del self.env[var]
        return _finite(total, self.expr)


def evaluate(expr, env):
    """算一个表达式。env：名字 → 数。错误一律 ExprError（一句中文）。"""
    if not isinstance(expr, str) or not expr.strip():
        raise ExprError("表达式是空的")
    if len(expr) > MAX_LEN:
        raise ExprError(f"表达式太长（最多 {MAX_LEN} 个字符）")
    if not expr.isascii():
        raise ExprError(f"表达式只能用英文字符（{expr[:40]}）")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise ExprError(f"表达式写得不对（{expr[:60]}）") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ExprError(f"表达式太复杂（最多 {MAX_NODES} 个节点）")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not NAME_RE.match(node.id) and node.id not in RESERVED:
            raise ExprError(f"名字只能用小写字母开头（{node.id}）")
    return _Eval(expr, dict(env)).run(tree)


def parse_step(step):
    """「名 = 表达式」→ (名, 表达式)。"""
    m = STEP_RE.match(step or "")
    if not m or m.group(1) in RESERVED:
        raise ExprError(f"每一步要写成「名 = 表达式」（{str(step)[:60]}）")
    return m.group(1), m.group(2)


def run_steps(steps, params):
    """按顺序算完所有步骤。返回 [(名, 表达式, 值)]；参数名不能被重新赋值，同一个名字也不能赋两次。"""
    env = {k: float(v) for k, v in params.items()}
    out = []
    for step in steps:
        name, expr = parse_step(step)
        if name in env:
            raise ExprError(f"{name} 已经有值了，不能再赋一次")
        env[name] = evaluate(expr, env)
        out.append((name, expr, env[name]))
    if not out:
        raise ExprError("至少要有一步")
    return out


def names_in(expr):
    """表达式里用到的名字（给显示代入用）。"""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - RESERVED)

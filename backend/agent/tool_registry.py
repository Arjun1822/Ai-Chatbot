import ast
from datetime import datetime, timezone
import math
import operator
import re
import urllib.parse
import urllib.request
import json
from typing import Any, Callable, Dict, List, Optional
from agent.schemas import ToolDefinition, ToolParameter


class SafeMathEvaluator:
    """Safe mathematical expression evaluator using AST analysis without eval/exec."""

    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    ALLOWED_FUNCTIONS = {
        "sqrt": math.sqrt,
        "abs": abs,
        "round": round,
        "ceil": math.ceil,
        "floor": math.floor,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "exp": math.exp,
        "pi": math.pi,
        "e": math.e,
    }

    @classmethod
    def evaluate(cls, expression: str) -> float:
        if not expression or not expression.strip():
            raise ValueError("Expression cannot be empty.")
        clean_expr = expression.strip().replace("^", "**")
        if len(clean_expr) > 200:
            raise ValueError("Expression too long (max 200 characters).")
        try:
            tree = ast.parse(clean_expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid mathematical syntax: {e}")
        return cls._eval_node(tree.body)

    @classmethod
    def _eval_node(cls, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        elif isinstance(node, ast.Num):  # Python < 3.8 compatibility
            return node.n
        elif isinstance(node, ast.Name):
            name = node.id.lower()
            if name in cls.ALLOWED_FUNCTIONS and isinstance(cls.ALLOWED_FUNCTIONS[name], (int, float)):
                return cls.ALLOWED_FUNCTIONS[name]
            raise ValueError(f"Undefined mathematical identifier: '{node.id}'")
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in cls.OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            left = cls._eval_node(node.left)
            right = cls._eval_node(node.right)
            if op_type == ast.Pow:
                if abs(right) > 100 or abs(left) > 1e10:
                    raise ValueError("Exponentiation magnitude exceeds safe compute limits.")
            return cls.OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in cls.OPERATORS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            operand = cls._eval_node(node.operand)
            return cls.OPERATORS[op_type](operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Unsupported function invocation format.")
            func_name = node.func.id.lower()
            if func_name not in cls.ALLOWED_FUNCTIONS or not callable(cls.ALLOWED_FUNCTIONS[func_name]):
                raise ValueError(f"Function '{func_name}' is not in allowed mathematical functions.")
            args = [cls._eval_node(arg) for arg in node.args]
            return cls.ALLOWED_FUNCTIONS[func_name](*args)
        else:
            raise ValueError(f"Unsupported mathematical expression construct: {type(node).__name__}")


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def register(
        self,
        tool: Optional[ToolDefinition] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parameters: Optional[List[Any]] = None,
        handler: Optional[Callable[..., Any]] = None,
        requires_confirmation: bool = False,
    ):
        if tool is not None and isinstance(tool, ToolDefinition):
            self._tools[tool.name] = tool
            return

        if name and handler:
            param_objs = []
            for p in (parameters or []):
                if isinstance(p, ToolParameter):
                    param_objs.append(p)
                elif isinstance(p, dict):
                    param_objs.append(
                        ToolParameter(
                            name=p["name"],
                            type=p.get("type", "string"),
                            description=p.get("description", ""),
                            required=p.get("required", True),
                            enum=p.get("enum"),
                        )
                    )
            t_def = ToolDefinition(
                name=name,
                description=description or "",
                parameters=param_objs,
                handler=handler,
                requires_confirmation=requires_confirmation,
            )
            self._tools[name] = t_def

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        return [tool.to_gemini_schema() for tool in self._tools.values()]

    def get_gemini_declarations(self) -> List[Dict[str, Any]]:
        return self.get_schemas()

    def _register_default_tools(self):
        # 1. Calculator Tool
        self.register(
            ToolDefinition(
                name="calculator",
                description="Perform precise mathematical calculations. Accepts arithmetic expressions including addition, subtraction, multiplication, division, exponents, and standard functions (sqrt, sin, cos, abs, log, round).",
                parameters=[
                    ToolParameter(
                        name="expression",
                        type="string",
                        description="Mathematical expression to evaluate, e.g. '(48 / 6) + (12 * 7)' or 'sqrt(144) + 10'.",
                    )
                ],
                handler=self._tool_calculator,
            )
        )

        # 2. Date and Time Tool
        self.register(
            ToolDefinition(
                name="date_time",
                description="Get current date, time, calculate days between dates, or inspect day of week.",
                parameters=[
                    ToolParameter(
                        name="operation",
                        type="string",
                        description="Action to perform: 'current_time', 'days_between', or 'day_of_week'.",
                        enum=["current_time", "days_between", "day_of_week"],
                    ),
                    ToolParameter(
                        name="date1",
                        type="string",
                        description="Optional first date in YYYY-MM-DD format (for days_between or day_of_week).",
                        required=False,
                    ),
                    ToolParameter(
                        name="date2",
                        type="string",
                        description="Optional second date in YYYY-MM-DD format (for days_between).",
                        required=False,
                    ),
                ],
                handler=self._tool_date_time,
            )
        )

        # 3. Document Search Tool (RAG integration hooked via orchestrator / rag_service)
        self.register(
            ToolDefinition(
                name="document_search",
                description="Search user's uploaded knowledge base documents for relevant context, facts, and citations.",
                parameters=[
                    ToolParameter(
                        name="query",
                        type="string",
                        description="Semantic search query string to look up in the uploaded documents.",
                    ),
                    ToolParameter(
                        name="top_k",
                        type="integer",
                        description="Number of relevant document chunks to retrieve (default: 4).",
                        required=False,
                    ),
                ],
                handler=self._tool_document_search,
            )
        )

        # 4. Web Search Tool
        self.register(
            ToolDefinition(
                name="web_search",
                description="Search the web for up-to-date factual information, external documentation, or news.",
                parameters=[
                    ToolParameter(
                        name="query",
                        type="string",
                        description="Keywords or question to search the web for.",
                    )
                ],
                handler=self._tool_web_search,
            )
        )

        # 5. Weather Tool
        self.register(
            ToolDefinition(
                name="weather",
                description="Get current weather and temperature for a given city name using meteorological data.",
                parameters=[
                    ToolParameter(
                        name="city",
                        type="string",
                        description="Name of the city, e.g. 'Tokyo', 'London', 'San Francisco'.",
                    )
                ],
                handler=self._tool_weather,
            )
        )

    # --- Tool Implementations ---

    def _tool_calculator(self, expression: str, **kwargs) -> Dict[str, Any]:
        result = SafeMathEvaluator.evaluate(expression)
        return {
            "expression": expression,
            "result": result,
            "formatted": f"{result:g}" if isinstance(result, float) else str(result),
        }

    def _tool_date_time(self, operation: str = "current_time", date1: str = None, date2: str = None, **kwargs) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        if operation == "current_time":
            return {
                "utc_datetime": now.isoformat(),
                "utc_date": now.strftime("%Y-%m-%d"),
                "utc_time": now.strftime("%H:%M:%S UTC"),
                "day_of_week": now.strftime("%A"),
            }
        elif operation == "day_of_week":
            if not date1:
                return {"error": "date1 parameter (YYYY-MM-DD) is required for day_of_week."}
            d = datetime.strptime(date1.strip(), "%Y-%m-%d")
            return {"date": date1, "day_of_week": d.strftime("%A")}
        elif operation == "days_between":
            if not date1 or not date2:
                return {"error": "Both date1 and date2 parameters (YYYY-MM-DD) are required for days_between."}
            d1 = datetime.strptime(date1.strip(), "%Y-%m-%d")
            d2 = datetime.strptime(date2.strip(), "%Y-%m-%d")
            diff = abs((d2 - d1).days)
            return {"date1": date1, "date2": date2, "difference_in_days": diff}
        return {"error": f"Unknown date_time operation '{operation}'"}

    def _tool_document_search(self, query: str, top_k: int = 4, rag_service: Any = None, user_id: str = None, **kwargs) -> Dict[str, Any]:
        if rag_service is None:
            return {"query": query, "results": [], "message": "Knowledge base service is not attached or empty."}
        results = rag_service.search(query=query, top_k=top_k or 4, user_id=user_id)
        return {
            "query": query,
            "results_count": len(results),
            "results": results,
        }

    def _tool_web_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Perform web search via DuckDuckGo Instant Answer or structured API fallback."""
        clean_query = query.strip()
        encoded = urllib.parse.quote(clean_query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OrbitAIChat/2.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = []
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", clean_query),
                    "snippet": data.get("AbstractText"),
                    "url": data.get("AbstractURL", ""),
                    "source": data.get("AbstractSource", "DuckDuckGo"),
                })
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                        "snippet": topic.get("Text"),
                        "url": topic.get("FirstURL", ""),
                        "source": "Web Reference",
                    })

            if not results:
                return {
                    "query": clean_query,
                    "results_count": 0,
                    "results": [],
                    "note": f"No direct instant summary found for '{clean_query}'. Consider rephrasing query keywords.",
                }

            return {
                "query": clean_query,
                "results_count": len(results),
                "results": results,
            }
        except Exception as e:
            return {
                "query": clean_query,
                "results_count": 0,
                "results": [],
                "error": f"Search provider request failed: {str(e)}",
            }

    def _tool_weather(self, city: str, **kwargs) -> Dict[str, Any]:
        """Get live weather using Open-Meteo free geocoding and forecast API."""
        if not city or not city.strip():
            return {"error": "City name is required."}
        clean_city = city.strip()
        encoded_city = urllib.parse.quote(clean_city)

        try:
            # 1. Geocoding
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_city}&count=1&language=en&format=json"
            req = urllib.request.Request(geo_url, headers={"User-Agent": "OrbitAIChat/2.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                geo_data = json.loads(resp.read().decode("utf-8"))

            if not geo_data.get("results"):
                return {"city": clean_city, "error": f"City '{clean_city}' could not be located."}

            loc = geo_data["results"][0]
            lat = loc["latitude"]
            lon = loc["longitude"]
            city_name = loc.get("name", clean_city)
            country = loc.get("country", "")

            # 2. Weather Forecast
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m&timezone=auto"
            req2 = urllib.request.Request(weather_url, headers={"User-Agent": "OrbitAIChat/2.0"})
            with urllib.request.urlopen(req2, timeout=4.0) as resp2:
                w_data = json.loads(resp2.read().decode("utf-8"))

            current = w_data.get("current", {})
            return {
                "city": city_name,
                "country": country,
                "latitude": lat,
                "longitude": lon,
                "temperature_celsius": current.get("temperature_2m"),
                "apparent_temperature_celsius": current.get("apparent_temperature"),
                "relative_humidity_percent": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "timestamp": current.get("time"),
            }
        except Exception as e:
            return {"city": clean_city, "error": f"Weather lookup failed: {str(e)}"}

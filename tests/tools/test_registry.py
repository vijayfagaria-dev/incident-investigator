from investigator.domain.tools import ToolName

from .conftest import ToolsFactory


def test_every_tool_is_registered_with_a_strict_schema(tools: ToolsFactory) -> None:
    definitions = {d.name: d for d in tools().definitions(list(ToolName))}

    assert set(definitions) == set(ToolName)
    for definition in definitions.values():
        assert definition.description
        assert definition.parameters["type"] == "object"
        assert definition.parameters["additionalProperties"] is False
    logs = definitions[ToolName.QUERY_LOGS].parameters
    assert set(logs["required"]) == {"service", "start", "end"}


def test_agents_can_be_given_a_subset_of_tools(tools: ToolsFactory) -> None:
    subset = tools().definitions([ToolName.QUERY_METRICS, ToolName.QUERY_LOGS])

    assert [d.name for d in subset] == [ToolName.QUERY_LOGS, ToolName.QUERY_METRICS]

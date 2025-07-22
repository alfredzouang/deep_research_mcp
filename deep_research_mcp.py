# pylint: disable=line-too-long,useless-suppression
# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------

"""
DESCRIPTION:
    This sample demonstrates how to use Agent operations with the Deep Research tool from
    the Azure Agents service through the **asynchronous** Python client. Deep Research issues
    external Bing Search queries and invokes an LLM, so each run can take several minutes
    to complete.

    For more information see the Deep Research Tool document: https://aka.ms/agents-deep-research

USAGE:
    python sample_agents_deep_research_async.py

    Before running the sample:

    pip install azure-identity aiohttp
    pip install --pre azure-ai-projects

    Set these environment variables with your own values:
    1) PROJECT_ENDPOINT - The Azure AI Project endpoint, as found in the Overview
                          page of your Azure AI Foundry portal.
    2) MODEL_DEPLOYMENT_NAME - The deployment name of the arbitration AI model, as found under the "Name" column in
       the "Models + endpoints" tab in your Azure AI Foundry project.
    3) DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME - The deployment name of the Deep Research AI model, as found under the "Name" column in
       the "Models + endpoints" tab in your Azure AI Foundry project.
    4) BING_RESOURCE_NAME - The resource name of the Bing connection, you can find it in the "Connected resources" tab
       in the Management Center of your AI Foundry project.
"""

import asyncio
import os
from typing import Optional

from azure.ai.projects.aio import AIProjectClient
from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import DeepResearchTool, MessageRole, ThreadMessage
from azure.identity.aio import DefaultAzureCredential
from fastmcp import FastMCP, Context
from typing import Annotated, Literal
from pydantic import Field
import logging
from rich.logging import RichHandler

logging.basicConfig(
    format="[%(asctime)s - %(name)s:%(lineno)d - %(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[RichHandler()]
)

# Add the handler to the logger

logger = logging.getLogger(__name__)

from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Deep Research Server")

async def fetch_and_print_new_agent_response(
    thread_id: str,
    agents_client: AgentsClient,
    last_message_id: Optional[str] = None,
    ctx: Context = None,
) -> Optional[str]:
    response = await agents_client.messages.get_last_message_by_role(
        thread_id=thread_id,
        role=MessageRole.AGENT,
    )

    if not response or response.id == last_message_id:
        return last_message_id

    logger.info("\nAgent response:")
    logger.info("\n".join(t.text.value for t in response.text_messages))
    if ctx:
        await ctx.info("\nAgent response:"+"\n".join(t.text.value for t in response.text_messages))
    # Print citation annotations (if any)
    for ann in response.url_citation_annotations:
        logger.info(f"URL Citation: [{ann.url_citation.title}]({ann.url_citation.url})")
        if ctx:
            await ctx.info(f"URL Citation: [{ann.url_citation.title}]({ann.url_citation.url})")
    return response.id


def create_research_summary(message: ThreadMessage, filepath: str = "research_summary.md") -> None:
    if not message:
        logger.info("No message content provided, cannot create research summary.")
        return
    report_content = "\n\n".join([t.text.value.strip() for t in message.text_messages])
        # Write unique URL citations, if present
    if message.url_citation_annotations:
        report_content += "\n\n## References\n"
        seen_urls = set()
        for ann in message.url_citation_annotations:
            url = ann.url_citation.url
            title = ann.url_citation.title or url
            if url not in seen_urls:
                report_content += f"- [{title}]({url})\n"
                seen_urls.add(url)

    logger.info(f"Research report content:\n{report_content}")
    return report_content

@mcp.tool(
        name="retrieve_deep_research_report",
        description="Retrieve a Deep Research report on a specific topic based on user input.",
)
async def retrieve_deep_research_report(
    research_topic: Annotated[str, Field(description="The topic to research")],
    ctx: Context,
    report_type: Annotated[Literal['brief', 'medium', 'comprehensive'], Field(description="The type of report to generate, one of ('brief', 'medium', 'comprehensive')")] = "comprehensive",
    language: Annotated[str, Field(description="The language to use for the report in ISO 639-1 format, e.g., 'en' for English, 'zh' for Chinese")] = "en",
    other_instructions: Optional[Annotated[str, Field(description="Additional instructions for the agent, if any")]] = None,
) -> str:

    project_client = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )

    bing_connection = await project_client.connections.get(name=os.environ["BING_RESOURCE_NAME"])

    # Initialize a Deep Research tool with Bing Connection ID and Deep Research model deployment name
    deep_research_tool = DeepResearchTool(
        bing_grounding_connection_id=bing_connection.id,
        deep_research_model=os.environ["DEEP_RESEARCH_MODEL_DEPLOYMENT_NAME"],
    )

    async with project_client:

        agents_client = project_client.agents

        # Create a new agent that has the Deep Research tool attached.
        # NOTE: To add Deep Research to an existing agent, fetch it with `get_agent(agent_id)` and then,
        # update the agent with the Deep Research tool.
        agent = await agents_client.create_agent(
            model=os.environ["MODEL_DEPLOYMENT_NAME"],
            name="my-agent",
            instructions="You are a helpful Agent that assists in researching topics that user provides.",
            tools=deep_research_tool.definitions,
        )
        await ctx.info("Agent created.")
        logger.info(f"Created agent, ID: {agent.id}")

        # Create thread for communication
        thread = await agents_client.threads.create()
        await ctx.info("Thread created.")
        logger.info(f"Created thread, ID: {thread.id}")

        # Format Instructions

        report_instructions_template = """
        Provide a {report_type} report on the topic: '{research_topic}'.
        Use the language {language} for the report.
        Do not ask the user for any additional information, just provide the report.
        """

        report_instructions = report_instructions_template.format(
            report_type=report_type,
            research_topic=research_topic,
            language=language,
        ) if not other_instructions else report_instructions_template.format(
            report_type=report_type,
            research_topic=research_topic,
            language=language,
        )+ f"# Other Instructions\n\n{other_instructions}\n\n"
        # Create message to thread
        message = await agents_client.messages.create(
            thread_id=thread.id,
            role="user",
            content=(
                report_instructions
            ),
        )
        logger.info(f"Created message, ID: {message.id}")

        await ctx.info("Starting the research process... this may take a few minutes. Be patient!")
        logger.info("Start processing the message... this may take a few minutes to finish. Be patient!")
        # Poll the run as long as run status is queued or in progress
        run = await agents_client.runs.create(thread_id=thread.id, agent_id=agent.id)
        last_message_id: Optional[str] = None
        while run.status in ("queued", "in_progress"):
            await asyncio.sleep(10)
            run = await agents_client.runs.get(thread_id=thread.id, run_id=run.id)

            last_message_id = await fetch_and_print_new_agent_response(
                thread_id=thread.id,
                agents_client=agents_client,
                last_message_id=last_message_id,
                ctx=ctx,
            )
            logger.info(f"Run status: {run.status}")
            await ctx.info(f"Run status: {run.status}")

        logger.info(f"Run finished with status: {run.status}, ID: {run.id}")
        await ctx.info(f"Run finished with status: {run.status}")

        if run.status == "failed":
            logger.info(f"Run failed: {run.last_error}")
            await ctx.error(f"Run failed: {run.last_error}")

        # Fetch the final message from the agent in the thread and create a research summary
        final_message = await agents_client.messages.get_last_message_by_role(
            thread_id=thread.id, role=MessageRole.AGENT
        )
        if final_message:
            report_content = create_research_summary(final_message)

        # Clean-up and delete the agent once the run is finished.
        # NOTE: Comment out this line if you plan to reuse the agent later.
        await agents_client.delete_agent(agent.id)
        logger.info("Deleted agent")
        return report_content or "No report content generated."

async def main():
    # Run the MCP server
    await mcp.run_async(transport="http", host="0.0.0.0", port=8001)

if __name__ == "__main__":
    asyncio.run(main())
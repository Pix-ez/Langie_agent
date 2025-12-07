# agent_brain.py
import os
import json
from typing import List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv() 

#put OpenAI API key in .env file
class ToolSelection(BaseModel):
    selected_tool: str = Field(description="The exact name of the tool to use from the available options")
    reasoning: str = Field(description="Why this tool was selected based on the input context")

class MatchReasoning(BaseModel):
    score: float = Field(description="Match score between 0.0 and 1.0")
    reasoning: str = Field(description="Explanation of the match logic, mentioning discrepancies if any")
    decision: str = Field(description="MATCHED or FAILED")

class LangieBrain:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4.1", temperature=0)
        self.system_prompt = """
        You are Langie the Invoice Processing LangGraph Agent.
        You think in structured stages.
        Each node is a well-defined processing phase.
        You always carry forward state variables between nodes.
        You know when to execute deterministic steps and when to choose dynamically.
        You orchestrate MCP clients to call COMMON or ATLAS abilities as required.
        You use Bigtool whenever a tool must be selected from a pool.
        You log every decision, every tool choice, and every state update.
        You always produce clean structured output.
        """

    # def select_tool(self, stage: str, available_tools: List[str], context: Dict) -> Dict:
    #     """
    #     Asks Langie to pick a tool dynamically based on context.
    #     """
    #     query = f"""
    #     STAGE: {stage}
    #     CONTEXT: {json.dumps(context)}
    #     AVAILABLE_POOLS: {available_tools}
        
    #     Task: Analyze the context (file types, vendor history, amounts) and select the best tool from the pool.
    #     """
        
    #     messages = [
    #         SystemMessage(content=self.system_prompt),
    #         HumanMessage(content=query)
    #     ]
        
    #     # Use Structured Output to enforce JSON
    #     structured_llm = self.llm.with_structured_output(ToolSelection)
    #     result = structured_llm.invoke(messages)
        
    #     return {"tool": result.selected_tool, "reasoning": result.reasoning}
    def select_tool(self, stage: str, tool_pool: List[str], context: Dict[str, Any]) -> Dict[str, str]:
        """
        Decides which tool to use.
        
        Args:
            stage: The current workflow stage (e.g., 'UNDERSTAND').
            tool_pool: List of available tool names (e.g., ['gpt-4o', 'tesseract']).
            context: Dictionary containing relevant file/invoice metadata.
        """
        # Construct the prompt
        query = f"""
        CURRENT STAGE: {stage}
        AVAILABLE TOOL POOL: {json.dumps(tool_pool)}
        
        CONTEXT DATA:
        {json.dumps(context, indent=2)}
        
        INSTRUCTIONS:
        Analyze the context. 
        - If the file is a complex PDF or image, prefer AI-heavy tools (gpt-4o, aws_textract).
        - If the file is simple text or the vendor is known for clean data, use lighter tools (tesseract).
        - For ERP, pick the connector that matches the vendor's segment if specified, otherwise default to the most robust one.
        
        Select the best tool from the pool.
        """
        
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=query)
        ]
        
        # Enforce Structure
        structured_llm = self.llm.with_structured_output(ToolSelection)
        result = structured_llm.invoke(messages)
        
        # Fallback safety: If LLM hallucinates a tool not in pool, pick the first one
        final_tool = result.selected_tool
        if final_tool not in tool_pool:
            final_tool = tool_pool[0]
            result.reasoning += f" (Auto-corrected from invalid choice: {result.selected_tool})"

        return {
            "tool": final_tool,
            "reasoning": result.reasoning
        }
    
    def semantic_match(self, invoice_data: Dict, po_data: Dict) -> Dict:
        """
        Asks Langie to perform semantic matching (better than strict math).
        e.g., matching "Cloud Hosting" to "Hosting Subscription".
        """
        query = f"""
        STAGE: MATCH_TWO_WAY
        
        INVOICE DATA: {json.dumps(invoice_data)}
        PO DATA: {json.dumps(po_data)}
        
        Task: 
        1. Compare Line Items semantically (e.g., 'Setup Fee' == 'Onboarding').
        2. Compare Totals (Allow for small tax variances if tax is explained).
        3. Determine a match score (0.0 to 1.0).
        4. Decide if it is MATCHED (>= 0.9) or FAILED.
        """
        
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=query)
        ]
        
        structured_llm = self.llm.with_structured_output(MatchReasoning)
        result = structured_llm.invoke(messages)
        
        return {
            "score": result.score, 
            "notes": result.reasoning, 
            "result": result.decision
        }

# Singleton Instance
langie = LangieBrain()
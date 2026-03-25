"""
AI Response Formatter
Format response types consistently for AI chat API
"""

from typing import Dict, Any, List, Optional


def text_response(message: str) -> Dict[str, Any]:
    """
    Simple text response.
    
    Args:
        message: Text message to return
        
    Returns:
        Response dict with type="text"
    """
    return {
        "type": "text",
        "text": message
    }


def execution_response(progress: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    """
    Tool execution response with progress details.
    
    Args:
        progress: List of execution steps/results
        text: Summary text
        
    Returns:
        Response dict with type="execution"
    """
    return {
        "type": "execution",
        "progress": progress,
        "text": text
    }


def selection_response(
    message: str,
    options: List[Dict[str, Any]],
    intent: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Response requesting user selection from options.
    
    Args:
        message: Prompt message
        options: List of options [{"label": str, "value": str}]
        intent: Original intent to execute after selection
        
    Returns:
        Response dict with type="selection"
    """
    return {
        "type": "selection",
        "message": message,
        "options": options,
        "intent": intent  # {tool, args}
    }


def confirmation_response(message: str, intent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Response requesting user confirmation.
    
    Args:
        message: Confirmation prompt
        intent: Intent to execute after confirmation
        
    Returns:
        Response dict with type="confirmation"
    """
    return {
        "type": "confirmation",
        "message": message,
        "intent": intent  # {tool, args}
    }


def input_required_response(
    message: str,
    fields: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Response requesting additional input fields.
    
    Args:
        message: Prompt message
        fields: List of required fields [{"name": str, "label": str, "type": str, "required": bool}]
        
    Returns:
        Response dict with type="input_required"
    """
    return {
        "type": "input_required",
        "message": message,
        "fields": fields
    }


def error_response(message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Error response.
    
    Args:
        message: Error message
        details: Optional error details
        
    Returns:
        Response dict with type="error"
    """
    response = {
        "type": "error",
        "message": message
    }
    
    if details:
        response["details"] = details
    
    return response

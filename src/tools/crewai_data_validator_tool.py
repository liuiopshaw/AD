import json
# Import the json module, used to serialize validation results as JSON-formatted strings

from typing import Dict, Any
# Import the Dict and Any type annotations from the typing module

from crewai.tools import BaseTool
# Import the BaseTool base class from crewai.tools; all CrewAI tools must inherit from it

from pydantic import BaseModel, Field
# Import BaseModel and Field from pydantic, used to define the tool's input parameter model and field constraints

from src.tools.data_validator_tool import get_data_validator_tool
# Import the singleton getter function for the underlying data validation tool

class DataValidatorToolInput(BaseModel):
    """Data Validator Tool Input Model"""
    # Pydantic input model: defines the parameters accepted by the CrewAI wrapper layer

    data: Dict[str, Any] = Field(description="Data dictionary to validate")
    # The data dictionary to validate, a required parameter; key-value pairs contain the chemical data fields

    validation_type: str = Field(default="full", description="Validation type ('full', 'cid', 'cas', 'formula', 'h_statements', 'molecular_weight', 'material_id')")
    # Validation type, defaults to "full" (comprehensive validation);
    # optional single-item validation values: cid, cas, formula, h_statements, molecular_weight, material_id

class CrewAIDataValidatorTool(BaseTool):
    """CrewAI tool wrapper for validating chemical and material data"""
    # Wrapper class for the CrewAI data validation tool, inheriting from BaseTool
    # Purpose: wraps the underlying data validation functionality as a tool directly callable by CrewAI agents

    name: str = "Data Validator"
    # Tool name; CrewAI agents reference this tool by this name

    description: str = (
        "Validate authenticity and validity of chemical and material data. "
        "Can validate CID, CAS number, formula, molecular weight, hazard statements etc. "
        "Use when you need to verify if generated chemical data is authentic and valid."
    )
    # Tool description; CrewAI agents use it to decide when to invoke the tool;
    # states that it can validate data types such as CID, CAS number, molecular formula, molecular weight, and hazard statements

    args_schema: type[BaseModel] = DataValidatorToolInput
    # Specifies the tool's input parameter model; the CrewAI framework automatically validates parameters

    def _run(
        self,
        data: Dict[str, Any],
        validation_type: str = "full"
    ) -> str:
        """
        Execute data validation.
        # Core method that executes data validation

        Args:
            data: Data dictionary to validate
            # The data dictionary to validate
            validation_type: Validation type ("full", "cid", "cas", "formula", "h_statements", "molecular_weight", "material_id")
            # The validation type string

        Returns:
            JSON formatted validation result
            # The validation result as a JSON-formatted string
        """
        try:
            # Get the singleton instance of the underlying data validation tool
            tool = get_data_validator_tool()

            # ==================== Dispatch by validation type ====================
            # Routing logic: call the corresponding single-item validation method based on the user-specified validation_type
            # If the corresponding field is missing from the data, return an error message

            if validation_type == "cid":
                # Single-item validation: PubChem CID
                if "pubchem_cid" in data:
                    result = tool.validate_cid(data["pubchem_cid"])
                else:
                    result = {"error": "pubchem_cid field not found in data"}

            elif validation_type == "cas":
                # Single-item validation: CAS registry number
                if "cas_number" in data:
                    result = tool.validate_cas_number(data["cas_number"])
                else:
                    result = {"error": "cas_number field not found in data"}

            elif validation_type == "formula":
                # Single-item validation: molecular formula
                if "molecular_formula" in data:
                    result = tool.validate_molecular_formula(data["molecular_formula"])
                else:
                    result = {"error": "molecular_formula field not found in data"}

            elif validation_type == "h_statements":
                # Single-item validation: GHS hazard statement codes
                if "hazard_statements" in data:
                    result = tool.validate_h_statements(data["hazard_statements"])
                else:
                    result = {"error": "hazard_statements field not found in data"}

            elif validation_type == "molecular_weight":
                # Single-item validation: molecular weight
                if "molecular_weight" in data:
                    result = tool.validate_molecular_weight(data["molecular_weight"])
                else:
                    result = {"error": "molecular_weight field not found in data"}

            elif validation_type == "material_id":
                # Single-item validation: Materials Project material ID
                if "material_id" in data:
                    result = tool.validate_material_id(data["material_id"])
                else:
                    result = {"error": "material_id field not found in data"}

            else:
                # Default: run comprehensive validation (validation_type == "full" or any other unrecognized value)
                # This validates every field present in the data one by one and returns a combined result
                result = tool.validate_chemical_data(data)

            # Serialize the validation result (dict) to a JSON string and return it
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            # Catch all exceptions and return the error information as JSON
            # Ensures CrewAI agents always receive a uniformly formatted response, so the workflow is not interrupted by uncaught exceptions
            return json.dumps({"error": f"Validation error: {str(e)}"}, ensure_ascii=False)

# ==================== Global tool instance ====================
# Create an instance of the CrewAI data validation tool for direct reference in Agent configuration
# Instantiated at module load time because the tool itself is stateless and instantiation overhead is negligible
data_validator_tool = CrewAIDataValidatorTool()

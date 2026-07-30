"""Tool search and installation manager."""

import os
import sys
import importlib
import subprocess
from pathlib import Path
from typing import Optional

from ..utils.i18n import i18n


# Common tool repositories (package name -> pip install command)
KNOWN_TOOLS = {
    "requests": "requests",
    "beautifulsoup4": "beautifulsoup4",
    "bs4": "beautifulsoup4",
    "selenium": "selenium",
    "pandas": "pandas",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "pillow": "pillow",
    "PIL": "pillow",
    "flask": "flask",
    "django": "django",
    "fastapi": "fastapi",
    "sqlalchemy": "sqlalchemy",
    "pytest": "pytest",
    "black": "black",
    "pylint": "pylint",
    "mypy": "mypy",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "click": "click",
    "rich": "rich",
    "pyyaml": "pyyaml",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "scipy": "scipy",
    "torch": "torch",
    "tensorflow": "tensorflow",
}


class ToolInstaller:
    """Manages tool search and installation."""
    
    def __init__(self):
        self._installed_cache = set()
    
    def is_package_installed(self, package_name: str) -> bool:
        """Check if a Python package is installed."""
        try:
            importlib.import_module(package_name)
            return True
        except ImportError:
            return False
    
    def find_tool_package(self, tool_name: str) -> Optional[str]:
        """Find the pip package for a tool name."""
        # Check known tools
        lower_name = tool_name.lower()
        for key, package in KNOWN_TOOLS.items():
            if key.lower() == lower_name:
                return package
        
        # Try common patterns
        return tool_name.lower().replace("-", "_")
    
    def install_package(self, package_name: str) -> tuple[bool, str]:
        """Install a Python package using pip."""
        try:
            # Use the same Python executable
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr
        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except Exception as e:
            return False, str(e)
    
    def search_and_install(self, tool_name: str) -> tuple[bool, str]:
        """Search for and install a tool."""
        # First check if already installed
        if self.is_package_installed(tool_name):
            return True, f"Package '{tool_name}' is already installed"
        
        # Find the package name
        package_name = self.find_tool_package(tool_name)
        if not package_name:
            return False, f"Could not find package for tool '{tool_name}'"
        
        # Install the package
        success, output = self.install_package(package_name)
        if success:
            self._installed_cache.add(tool_name)
            return True, f"Successfully installed '{package_name}'"
        else:
            return False, f"Failed to install '{package_name}': {output}"
    
    def get_install_suggestion(self, tool_name: str) -> str:
        """Get a suggestion for installing a tool."""
        package_name = self.find_tool_package(tool_name)
        if package_name:
            return f"pip install {package_name}"
        return f"pip install {tool_name}"


# Global instance
tool_installer = ToolInstaller()

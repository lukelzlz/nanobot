"""Skills loader for agent capabilities."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.

    Skills can have different types:
    - "instruction" (default): Standard instruction-based skills
    - "mcp": MCP-driven skills that require MCP servers
    - "hybrid": Combination of instruction and MCP tools
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = []

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        # Filter by requirements
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self, mcp_status: dict[str, bool] | None = None) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Args:
            mcp_status: Optional dict of MCP server connection status.

        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            # Check MCP requirements
            skill_type = self.get_skill_type(s["name"])
            mcp_servers = self.get_mcp_servers(s["name"])

            # For MCP skills, check if servers are connected
            mcp_available = True
            if mcp_servers and mcp_status is not None:
                mcp_available = all(mcp_status.get(server, False) for server in mcp_servers)
                available = available and mcp_available

            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # Add skill type
            if skill_type != "instruction":
                lines.append(f"    <type>{escape_xml(skill_type)}</type>")

            # Add MCP servers if any
            if mcp_servers:
                lines.append(f"    <mcp_servers>{escape_xml(', '.join(mcp_servers))}</mcp_servers>")

            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")
                # Check MCP specifically
                if mcp_servers and not mcp_available:
                    lines.append(f"    <requires>MCP servers: {escape_xml(', '.join(mcp_servers))}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """Parse nanobot metadata JSON from frontmatter."""
        try:
            data = json.loads(raw)
            return data.get("nanobot", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                return self._parse_yaml_frontmatter(match.group(1))

        return None

    def _parse_yaml_frontmatter(self, yaml_str: str) -> dict[str, Any]:
        """
        Parse YAML frontmatter into a dictionary.

        Handles strings, numbers, booleans, lists, and nested structures.
        """
        result: dict[str, Any] = {}

        for line in yaml_str.split("\n"):
            if not line.strip() or line.strip().startswith("#"):
                continue

            if ":" in line:
                key, value_part = line.split(":", 1)
                key = key.strip()
                value = value_part.strip()

                # Handle empty values (use in nested structures)
                if not value:
                    continue

                # Handle boolean
                if value.lower() in ("true", "yes", "on"):
                    result[key] = True
                elif value.lower() in ("false", "no", "off"):
                    result[key] = False

                # Handle numbers
                elif value.isdigit():
                    result[key] = int(value)
                elif value.lstrip("-").isdigit():
                    result[key] = int(value)

                # Handle quoted strings
                elif value.startswith('"') and value.endswith('"'):
                    result[key] = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    result[key] = value[1:-1]

                # Handle list syntax (starting with -)
                elif value.startswith("-"):
                    items = []
                    # Collect all list items
                    for list_line in yaml_str.split("\n"):
                        if list_line.strip().startswith("-"):
                            item = list_line.split("-", 1)[1].strip().strip('"\'')
                            items.append(item)
                        elif list_line.strip() and not list_line.startswith(" "):
                            # End of list
                            break
                    result[key] = items

                # Handle environment dictionary syntax (ENV_VAR: value)
                elif "=" in value or (key in ("env", "requires", "metadata") and any(k in yaml_str for k in ["bins", "env"])):
                    # Try to parse as nested structure
                    if key == "requires":
                        # Parse requires section
                        result[key] = self._parse_requires_section(yaml_str)
                    elif key == "mcp_servers" and value.startswith("["):
                        # Parse list syntax
                        result[key] = self._parse_list_value(value)
                    elif key == "type":
                        result[key] = value
                    else:
                        result[key] = value

                else:
                    result[key] = value

        return result

    def _parse_requires_section(self, yaml_str: str) -> dict[str, list[str]]:
        """Parse the 'requires' section of frontmatter."""
        result: dict[str, list[str]] = {"bins": [], "env": []}

        in_requires = False
        current_key = None

        for line in yaml_str.split("\n"):
            stripped = line.strip()

            if stripped.startswith("requires:"):
                in_requires = True
                continue

            if in_requires:
                if stripped.startswith("bins:"):
                    current_key = "bins"
                elif stripped.startswith("env:"):
                    current_key = "env"
                elif stripped.startswith("-") and current_key:
                    item = stripped.split("-", 1)[1].strip().strip('"\'')
                    result[current_key].append(item)
                elif not stripped.startswith(" ") and not stripped.startswith("-"):
                    # End of requires section
                    break

        return result

    def _parse_list_value(self, value: str) -> list[str]:
        """Parse a list value like [item1, item2]."""
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            if not inner.strip():
                return []
            return [item.strip().strip('"\'') for item in inner.split(",")]
        return []

    def get_skill_type(self, name: str) -> str:
        """
        Get the type of a skill.

        Args:
            name: Skill name.

        Returns:
            Skill type: "instruction", "mcp", "hybrid", or "instruction" (default).
        """
        meta = self.get_skill_metadata(name)
        if not meta:
            return "instruction"

        skill_type = meta.get("type", "instruction")
        # Validate type
        if skill_type not in ("instruction", "mcp", "hybrid"):
            return "instruction"
        return skill_type

    def get_mcp_servers(self, name: str) -> list[str]:
        """
        Get the list of MCP servers required by a skill.

        Args:
            name: Skill name.

        Returns:
            List of MCP server names.
        """
        meta = self.get_skill_metadata(name)
        if not meta:
            return []

        # Check for mcp_servers field
        mcp_servers = meta.get("mcp_servers")
        if isinstance(mcp_servers, list):
            return mcp_servers
        elif isinstance(mcp_servers, str) and mcp_servers:
            return [mcp_servers]

        # Check in metadata.nanobot field
        metadata_raw = meta.get("metadata", "")
        skill_meta = self._parse_nanobot_metadata(metadata_raw)
        mcp_servers = skill_meta.get("mcp_servers")
        if isinstance(mcp_servers, list):
            return mcp_servers

        return []

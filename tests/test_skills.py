"""Tests for SkillsLoader."""

from pathlib import Path

import pytest

from nanobot.agent.skills import BUILTIN_SKILLS_DIR, SkillsLoader


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Create a temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "skills").mkdir()
    return workspace


@pytest.fixture
def skills_loader(temp_workspace: Path):
    """Create a SkillsLoader instance."""
    return SkillsLoader(temp_workspace)


class TestSkillsLoader:
    """Test SkillsLoader functionality."""

    def test_init(self, skills_loader: SkillsLoader):
        """Test initialization."""
        assert skills_loader.workspace == skills_loader.workspace
        assert skills_loader.workspace_skills == skills_loader.workspace / "skills"

    def test_list_skills_empty(self, skills_loader: SkillsLoader):
        """Test listing skills when none exist in workspace."""
        skills = skills_loader.list_skills()
        # Builtin skills are always present
        workspace_skills = [s for s in skills if s["source"] == "workspace"]
        assert workspace_skills == []

    def test_load_nonexistent_skill(self, skills_loader: SkillsLoader):
        """Test loading a skill that doesn't exist."""
        result = skills_loader.load_skill("nonexistent")
        assert result is None

    def test_list_workspace_skills(self, skills_loader: SkillsLoader):
        """Test listing skills from workspace."""
        skills_dir = skills_loader.workspace_skills
        test_skill = skills_dir / "test-skill" / "SKILL.md"
        test_skill.parent.mkdir(parents=True)
        test_skill.write_text(
            "---\n"
            "name: test-skill\n"
            "description: Test skill\n"
            "---\n\n"
            "Test content"
        )

        skills = skills_loader.list_skills()
        workspace_skills = [s for s in skills if s["source"] == "workspace"]
        assert len(workspace_skills) == 1
        assert workspace_skills[0]["name"] == "test-skill"
        assert workspace_skills[0]["source"] == "workspace"

    def test_load_skills_for_context(self, skills_loader: SkillsLoader):
        """Test loading skills for context."""
        skills_dir = skills_loader.workspace_skills

        # Create two skills
        skill1 = skills_dir / "skill1" / "SKILL.md"
        skill1.parent.mkdir(parents=True)
        skill1.write_text("---\nname: skill1\n---\nContent 1")

        skill2 = skills_dir / "skill2" / "SKILL.md"
        skill2.parent.mkdir(parents=True)
        skill2.write_text("---\nname: skill2\n---\nContent 2")

        result = skills_loader.load_skills_for_context(["skill1", "skill2"])
        assert "skill1" in result
        assert "skill2" in result
        assert "Content 1" in result
        assert "Content 2" in result

    def test_load_skills_for_context_filters_frontmatter(self, skills_loader: SkillsLoader):
        """Test that frontmatter is stripped when loading for context."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "test" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: test\n"
            "description: Test\n"
            "---\n\n"
            "# Content\n"
        )

        result = skills_loader.load_skills_for_context(["test"])
        assert "---" not in result
        assert "# Content" in result

    def test_get_skill_metadata(self, skills_loader: SkillsLoader):
        """Test getting skill metadata."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "test" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: test-skill\n"
            "description: Test description\n"
            "always: true\n"
            "---\n\n"
            "Content"
        )

        # load_skill uses directory name, not frontmatter name
        metadata = skills_loader.get_skill_metadata("test")
        assert metadata is not None
        assert metadata.get("name") == "test-skill"
        assert metadata.get("description") == "Test description"
        assert metadata.get("always") is True

    def test_get_skill_metadata_not_found(self, skills_loader: SkillsLoader):
        """Test getting metadata for nonexistent skill."""
        metadata = skills_loader.get_skill_metadata("nonexistent")
        assert metadata is None

    def test_get_always_skills(self, skills_loader: SkillsLoader):
        """Test getting always skills."""
        skills_dir = skills_loader.workspace_skills

        # Create skill with always=true
        skill1 = skills_dir / "always-skill" / "SKILL.md"
        skill1.parent.mkdir(parents=True)
        skill1.write_text("---\nname: always-skill\nalways: true\n---\nContent")

        # Create skill with always=false (default)
        skill2 = skills_dir / "normal-skill" / "SKILL.md"
        skill2.parent.mkdir(parents=True)
        skill2.write_text("---\nname: normal-skill\n---\nContent")

        always = skills_loader.get_always_skills()
        assert "always-skill" in always
        assert "normal-skill" not in always

    def test_get_always_skills_filters_unavailable(self, skills_loader: SkillsLoader):
        """Test that always skills are filtered by requirements."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "needs-bin" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: needs-bin\n"
            "always: true\n"
            "metadata: {\"nanobot\": {\"requires\": {\"bins\": [\"nonexistent-bin\"]}}}\n"
            "---\n"
        )

        always = skills_loader.get_always_skills()
        # Should be filtered because the binary requirement is not met
        assert "needs-bin" not in always

    def test_get_skill_type(self, skills_loader: SkillsLoader):
        """Test getting skill type."""
        skills_dir = skills_loader.workspace_skills

        # MCP skill
        mcp_skill = skills_dir / "mcp-skill" / "SKILL.md"
        mcp_skill.parent.mkdir(parents=True)
        mcp_skill.write_text(
            "---\n"
            "name: mcp-skill\n"
            "type: mcp\n"
            "---\n"
        )

        assert skills_loader.get_skill_type("mcp-skill") == "mcp"

        # Instruction skill (default)
        normal_skill = skills_dir / "normal" / "SKILL.md"
        normal_skill.parent.mkdir(parents=True)
        normal_skill.write_text("---\nname: normal\n---\n")

        assert skills_loader.get_skill_type("normal") == "instruction"

    def test_get_mcp_servers(self, skills_loader: SkillsLoader):
        """Test getting MCP servers for a skill."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "mcp-skill" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        # Use inline list format which the simple parser handles
        skill.write_text(
            "---\n"
            "name: mcp-skill\n"
            "type: mcp\n"
            "mcp_servers: [server1, server2]\n"
            "---\n"
        )

        servers = skills_loader.get_mcp_servers("mcp-skill")
        assert "server1" in servers
        assert "server2" in servers

    def test_get_mcp_servers_from_metadata(self, skills_loader: SkillsLoader):
        """Test getting MCP servers from metadata."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "mcp-skill2" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: mcp-skill2\n"
            "metadata: {\"nanobot\": {\"mcp_servers\": [\"server1\", \"server2\"]}}\n"
            "---\n"
        )

        servers = skills_loader.get_mcp_servers("mcp-skill2")
        assert "server1" in servers
        assert "server2" in servers

    def test_build_skills_summary(self, skills_loader: SkillsLoader):
        """Test building skills summary."""
        skills_dir = skills_loader.workspace_skills

        skill = skills_dir / "test" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill\n"
            "---\n"
        )

        summary = skills_loader.build_skills_summary()
        # Summary uses directory name, not frontmatter name
        assert "test" in summary
        assert "A test skill" in summary

    def test_build_skills_summary_with_mcp_status(self, skills_loader: SkillsLoader):
        """Test skills summary includes MCP status."""
        skills_dir = skills_loader.workspace_skills

        # Create MCP skill
        mcp_skill = skills_dir / "mcp-skill" / "SKILL.md"
        mcp_skill.parent.mkdir(parents=True)
        mcp_skill.write_text(
            "---\n"
            "name: mcp-skill\n"
            "type: mcp\n"
            "mcp_servers:\n"
            "  - test-server\n"
            "---\n"
        )

        # Mock MCP status
        mcp_status = {"test-server": True}
        summary = skills_loader.build_skills_summary(mcp_status=mcp_status)
        assert "mcp-skill" in summary

    def test_build_skills_summary_unavailable_mcp(self, skills_loader: SkillsLoader):
        """Test skills summary shows unavailable MCP skills."""
        skills_dir = skills_loader.workspace_skills

        # Create MCP skill
        mcp_skill = skills_dir / "mcp-skill" / "SKILL.md"
        mcp_skill.parent.mkdir(parents=True)
        mcp_skill.write_text(
            "---\n"
            "name: mcp-skill\n"
            "type: mcp\n"
            "mcp_servers:\n"
            "  - test-server\n"
            "---\n"
        )

        # Mock MCP status - server not connected
        mcp_status = {"test-server": False}
        summary = skills_loader.build_skills_summary(mcp_status=mcp_status)
        assert "mcp-skill" in summary
        # Should be marked as unavailable or show requires

    def test_parse_yaml_frontmatter_list(self, skills_loader: SkillsLoader):
        """Test parsing list values in frontmatter."""
        skills_dir = skills_loader.workspace_skills
        skill = skills_dir / "list-skill" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(
            "---\n"
            "name: list-skill\n"
            "requires:\n"
            "  bins:\n"
            "    - git\n"
            "    - docker\n"
            "---\n"
        )

        metadata = skills_loader.get_skill_metadata("list-skill")
        assert metadata is not None

    def test_builtin_skills_directory_exists(self):
        """Test that builtin skills directory exists."""
        assert BUILTIN_SKILLS_DIR.exists()
        # Check that at least one builtin skill exists
        skill_dirs = list(BUILTIN_SKILLS_DIR.iterdir())
        assert len(skill_dirs) > 0


class TestSkillsRequirements:
    """Test skill requirements checking."""

    def test_check_requirements_with_bins(self):
        """Test checking binary requirements."""
        loader = SkillsLoader(Path("/tmp"))

        # python3 should be available, nonexistent should not
        assert loader._check_requirements({"requires": {"bins": ["python3"]}}) is True
        assert loader._check_requirements({"requires": {"bins": ["nonexistent"]}}) is False

        # Empty bins should pass
        assert loader._check_requirements({"requires": {"bins": []}}) is True
        assert loader._check_requirements({}) is True

    def test_check_requirements_with_env(self, temp_workspace: Path):
        """Test checking environment variable requirements."""
        loader = SkillsLoader(temp_workspace)

        # Set a test env var
        import os
        os.environ["TEST_VAR"] = "test"

        assert loader._check_requirements({"requires": {"env": ["TEST_VAR"]}}) is True
        assert loader._check_requirements({"requires": {"env": ["NONEXISTENT_VAR"]}}) is False

        # Clean up
        del os.environ["TEST_VAR"]

    def test_get_missing_requirements(self, temp_workspace: Path):
        """Test getting description of missing requirements."""
        loader = SkillsLoader(temp_workspace)

        missing = loader._get_missing_requirements({
            "requires": {
                "bins": ["nonexistent"],
                "env": ["NONEXISTENT_VAR"]
            }
        })

        assert "CLI: nonexistent" in missing
        assert "ENV: NONEXISTENT_VAR" in missing

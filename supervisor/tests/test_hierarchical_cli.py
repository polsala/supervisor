"""Integration tests for hierarchical CLI functionality."""

import unittest
from unittest.mock import Mock, MagicMock
from supervisor.supervisorctl import DefaultControllerPlugin
from supervisor.options import ClientOptions


class MockController:
    """Mock controller for testing."""
    def __init__(self):
        self.output_lines = []
        self.exitstatus = 0
        self.options = ClientOptions()
        
    def output(self, line):
        self.output_lines.append(line)
        
    def upcheck(self):
        return True
        
    def get_supervisor(self):
        return self.supervisor


class TestHierarchicalCLI(unittest.TestCase):
    
    def setUp(self):
        self.ctl = MockController()
        self.plugin = DefaultControllerPlugin(self.ctl)
        
        # Mock supervisor with hierarchical support
        self.supervisor = Mock()
        self.ctl.supervisor = self.supervisor
        
        # Mock hierarchy data
        self.hierarchy_data = {
            'name': '<root>',
            'type': 'RootNode', 
            'path': '<root>',
            'children': {
                'frontend': {
                    'name': 'frontend',
                    'type': 'MultiGroupNode',
                    'path': 'frontend',
                    'children': {
                        'web': {
                            'name': 'web',
                            'type': 'GroupNode', 
                            'path': 'frontend.web',
                            'children': {
                                'nginx': {
                                    'name': 'nginx',
                                    'type': 'ProgramNode',
                                    'path': 'frontend.web.nginx',
                                    'children': {},
                                    'state': 'RUNNING',
                                    'pid': 1234
                                }
                            }
                        }
                    }
                }
            }
        }
        
        self.supervisor.getHierarchy.return_value = self.hierarchy_data
        self.supervisor.getAllProcessInfo.return_value = [
            {
                'name': 'nginx',
                'group': 'web',
                'statename': 'RUNNING',
                'pid': 1234,
                'description': 'running'
            }
        ]
        
    def test_groups_command_basic(self):
        """Test basic groups command."""
        self.plugin.do_groups('')
        
        # Should have called getHierarchy
        self.supervisor.getHierarchy.assert_called_once()
        
        # Should have some output
        self.assertTrue(len(self.ctl.output_lines) > 0)
        
    def test_groups_command_json(self):
        """Test groups command with JSON output."""
        self.plugin.do_groups('--json')
        
        # Should output JSON
        output = '\n'.join(self.ctl.output_lines)
        self.assertIn('"name"', output)
        self.assertIn('"type"', output)
        
    def test_groups_command_fallback(self):
        """Test groups command falls back when hierarchy not available."""
        # Remove getHierarchy method to simulate old server
        del self.supervisor.getHierarchy
        
        self.plugin.do_groups('')
        
        # Should have fallen back to flat display
        output = '\n'.join(self.ctl.output_lines)
        self.assertIn('not supported', output)
        
    def test_start_hierarchical_path(self):
        """Test start command with hierarchical path."""
        # Mock controlByPath method
        self.supervisor.controlByPath.return_value = [
            {
                'path': 'frontend.web.nginx',
                'name': 'nginx',
                'action': 'start', 
                'status': 'success'
            }
        ]
        
        self.plugin.do_start('frontend.web.nginx')
        
        # Should have called controlByPath
        self.supervisor.controlByPath.assert_called_once_with('start', ['frontend.web.nginx'])
        
        # Should show success message
        output = '\n'.join(self.ctl.output_lines)
        self.assertIn('started', output)
        
    def test_start_traditional_fallback(self):
        """Test start command falls back for traditional names."""
        # Mock traditional start methods
        self.supervisor.startProcess.return_value = True
        
        self.plugin.do_start('web:nginx')
        
        # Should have called traditional startProcess
        self.supervisor.startProcess.assert_called_once_with('web:nginx')
        
    def test_status_hierarchical_path(self):
        """Test status command with hierarchical path."""
        self.plugin.do_status('frontend.web')
        
        # Should have called getHierarchy
        self.supervisor.getHierarchy.assert_called_once()
        
        # Should show process status
        self.assertTrue(len(self.ctl.output_lines) > 0)


if __name__ == '__main__':
    unittest.main()
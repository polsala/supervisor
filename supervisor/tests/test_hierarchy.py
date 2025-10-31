"""Tests for supervisor.hierarchy module."""

import unittest
from supervisor.hierarchy import (
    HierarchyManager, RootNode, ProgramNode, GroupNode, MultiGroupNode,
    CycleError, DuplicateNameError, PathError, HierarchyError,
    split_namespec, make_namespec
)


class DummyProcessConfig(object):
    """Dummy process config for testing."""
    def __init__(self, name):
        self.name = name
        self.state = 'STOPPED'


class TestHierarchyNodes(unittest.TestCase):
    
    def test_node_creation(self):
        root = RootNode()
        self.assertEqual(root.name, '<root>')
        self.assertEqual(root.get_path(), '<root>')
        
        program = ProgramNode('test', DummyProcessConfig('test'))
        self.assertEqual(program.name, 'test')
        self.assertEqual(program.get_path(), 'test')
        
        group = GroupNode('frontend')
        self.assertEqual(group.name, 'frontend')
        self.assertEqual(group.get_path(), 'frontend')
        
        multigroup = MultiGroupNode('prod')
        self.assertEqual(multigroup.name, 'prod')
        self.assertEqual(multigroup.get_path(), 'prod')
        
    def test_node_hierarchy(self):
        root = RootNode()
        group = GroupNode('frontend')
        program = ProgramNode('nginx', DummyProcessConfig('nginx'))
        
        root.add_child(group)
        group.add_child(program)
        
        self.assertEqual(group.get_path(), 'frontend')
        self.assertEqual(program.get_path(), 'frontend.nginx')
        self.assertEqual(program.parent, group)
        self.assertEqual(group.parent, root)
        
    def test_duplicate_child_error(self):
        root = RootNode()
        group1 = GroupNode('test')
        group2 = GroupNode('test')
        
        root.add_child(group1)
        
        with self.assertRaises(DuplicateNameError):
            root.add_child(group2)
            
    def test_iter_descendants(self):
        root = RootNode()
        frontend = GroupNode('frontend')
        backend = GroupNode('backend')
        nginx = ProgramNode('nginx', DummyProcessConfig('nginx'))
        api = ProgramNode('api', DummyProcessConfig('api'))
        
        root.add_child(frontend)
        root.add_child(backend)
        frontend.add_child(nginx)
        backend.add_child(api)
        
        descendants = list(root.iter_descendants())
        self.assertEqual(len(descendants), 4)  # 2 groups + 2 programs
        
        # Test with predicate
        programs_only = list(root.iter_descendants(
            predicate=lambda n: isinstance(n, ProgramNode)))
        self.assertEqual(len(programs_only), 2)
        
        # Test with depth limit
        depth_1_only = list(root.iter_descendants(depth=1))
        self.assertEqual(len(depth_1_only), 2)  # Only direct children


class TestHierarchyManager(unittest.TestCase):
    
    def setUp(self):
        self.manager = HierarchyManager()
        
    def test_add_program(self):
        config = DummyProcessConfig('nginx')
        self.manager.add_program('frontend.web.nginx', config)
        
        program = self.manager.resolve_path('frontend.web.nginx')
        self.assertIsInstance(program, ProgramNode)
        self.assertEqual(program.name, 'nginx')
        self.assertEqual(program.get_path(), 'frontend.web.nginx')
        
    def test_add_group(self):
        group = self.manager.add_group('frontend', is_multigroup=True)
        self.assertIsInstance(group, MultiGroupNode)
        self.assertEqual(group.name, 'frontend')
        
        # Should return existing group when adding again
        same_group = self.manager.add_group('frontend', is_multigroup=True)
        self.assertEqual(group, same_group)
        
    def test_resolve_path(self):
        config = DummyProcessConfig('nginx')
        self.manager.add_program('frontend.web.nginx', config)
        
        # Test resolving program
        program = self.manager.resolve_path('frontend.web.nginx')
        self.assertEqual(program.name, 'nginx')
        
        # Test resolving group
        group = self.manager.resolve_path('frontend.web')
        self.assertEqual(group.name, 'web')
        
    def test_resolve_path_not_found(self):
        with self.assertRaises(PathError):
            self.manager.resolve_path('nonexistent.path')
            
    def test_simple_glob_resolution(self):
        config1 = DummyProcessConfig('nginx')
        config2 = DummyProcessConfig('apache')
        self.manager.add_program('frontend.web.nginx', config1)
        self.manager.add_program('frontend.web.apache', config2)
        
        # Test wildcard matching
        results = self.manager.resolve_path('frontend.web.*')
        self.assertEqual(len(results), 2)
        names = [node.name for node in results]
        self.assertIn('nginx', names)
        self.assertIn('apache', names)
        
    def test_recursive_glob_resolution(self):
        config1 = DummyProcessConfig('nginx')
        config2 = DummyProcessConfig('api')
        self.manager.add_program('frontend.web.nginx', config1)
        self.manager.add_program('backend.api.api', config2)
        
        # Test recursive glob
        results = self.manager.resolve_path('**.nginx')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, 'nginx')
        
        # Test all programs
        all_programs = self.manager.resolve_path('**')
        program_count = len([n for n in all_programs if isinstance(n, ProgramNode)])
        self.assertEqual(program_count, 2)
        
    def test_conflict_detection(self):
        # Program vs Group conflict
        config = DummyProcessConfig('test')
        self.manager.add_program('test', config)
        
        with self.assertRaises(HierarchyError):
            self.manager.add_group('test')
            
    def test_get_hierarchy_dict(self):
        config = DummyProcessConfig('nginx')
        self.manager.add_program('frontend.web.nginx', config)
        
        hierarchy = self.manager.get_hierarchy_dict()
        
        # Check structure
        self.assertEqual(hierarchy['name'], '<root>')
        self.assertIn('frontend', hierarchy['children'])
        frontend = hierarchy['children']['frontend']
        self.assertIn('web', frontend['children'])
        web = frontend['children']['web']
        self.assertIn('nginx', web['children'])
        nginx = web['children']['nginx']
        self.assertEqual(nginx['type'], 'ProgramNode')


class TestNameSpecUtils(unittest.TestCase):
    
    def test_split_namespec(self):
        # Test with group
        group, program = split_namespec('frontend.web:nginx')
        self.assertEqual(group, 'frontend.web')
        self.assertEqual(program, 'nginx')
        
        # Test without group
        group, program = split_namespec('nginx')
        self.assertIsNone(group)
        self.assertEqual(program, 'nginx')
        
    def test_make_namespec(self):
        # Test with group
        namespec = make_namespec('frontend.web', 'nginx')
        self.assertEqual(namespec, 'frontend.web:nginx')
        
        # Test without group
        namespec = make_namespec(None, 'nginx')
        self.assertEqual(namespec, 'nginx')


if __name__ == '__main__':
    unittest.main()
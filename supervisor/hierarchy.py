"""Hierarchical group support for Supervisor.

This module implements the data structures and algorithms for managing
hierarchical groups of programs in Supervisor, including tree representation,
path resolution, and glob pattern matching.
"""

import re
import fnmatch
from collections import defaultdict
from supervisor.compat import as_string


class HierarchyError(Exception):
    """Base exception for hierarchy-related errors."""
    pass


class CycleError(HierarchyError):
    """Raised when a cycle is detected in the hierarchy."""
    pass


class DuplicateNameError(HierarchyError):
    """Raised when duplicate child names exist in the same parent."""
    pass


class PathError(HierarchyError):
    """Raised when a path cannot be resolved."""
    pass


class Node(object):
    """Base class for all hierarchy nodes."""
    
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.children = {}  # name -> Node
        
    def add_child(self, child):
        """Add a child node."""
        if child.name in self.children:
            raise DuplicateNameError(
                f"Child '{child.name}' already exists in '{self.get_path()}'")
        self.children[child.name] = child
        child.parent = self
        
    def remove_child(self, name):
        """Remove a child node by name."""
        if name in self.children:
            child = self.children[name]
            child.parent = None
            del self.children[name]
            return child
        return None
        
    def get_path(self):
        """Get the full path from root to this node."""
        if self.parent is None or self.parent.name == '<root>':
            return self.name
        return f"{self.parent.get_path()}.{self.name}"
        
    def find_child(self, name):
        """Find a direct child by name."""
        return self.children.get(name)
        
    def iter_descendants(self, depth=None, predicate=None):
        """Iterate over all descendants, optionally filtering by depth and predicate."""
        if depth is not None and depth <= 0:
            return
            
        for child in self.children.values():
            if predicate is None or predicate(child):
                yield child
                
            next_depth = None if depth is None else depth - 1
            for descendant in child.iter_descendants(next_depth, predicate):
                yield descendant
                
    def __repr__(self):
        return f"<{self.__class__.__name__}(name='{self.name}', path='{self.get_path()}')>"


class RootNode(Node):
    """Root node of the hierarchy tree."""
    
    def __init__(self):
        super(RootNode, self).__init__('<root>')
        

class ProgramNode(Node):
    """Represents a program in the hierarchy."""
    
    def __init__(self, name, process_config, parent=None):
        super(ProgramNode, self).__init__(name, parent)
        self.process_config = process_config
        

class GroupNode(Node):
    """Represents a flat group of programs (traditional supervisor group)."""
    
    def __init__(self, name, parent=None):
        super(GroupNode, self).__init__(name, parent)
        

class MultiGroupNode(Node):
    """Represents a hierarchical group that can contain programs and other groups."""
    
    def __init__(self, name, parent=None):
        super(MultiGroupNode, self).__init__(name, parent)


class HierarchyManager(object):
    """Manages the hierarchical structure and provides path resolution."""
    
    def __init__(self):
        self.root = RootNode()
        self._path_cache = {}
        
    def clear(self):
        """Clear the hierarchy."""
        self.root = RootNode()
        self._path_cache = {}
        
    def add_program(self, path, process_config):
        """Add a program at the given path."""
        parts = self._parse_path(path)
        parent = self._ensure_path_exists(parts[:-1])
        
        program_name = parts[-1]
        if program_name in parent.children:
            existing = parent.children[program_name]
            if not isinstance(existing, ProgramNode):
                raise HierarchyError(
                    f"Cannot add program '{program_name}' at '{path}': "
                    f"name conflicts with existing {existing.__class__.__name__}")
        
        program = ProgramNode(program_name, process_config, parent)
        parent.add_child(program)
        self._invalidate_cache()
        
    def add_group(self, path, is_multigroup=False):
        """Add a group at the given path."""
        parts = self._parse_path(path)
        parent = self._ensure_path_exists(parts[:-1])
        
        group_name = parts[-1]
        if group_name in parent.children:
            existing = parent.children[group_name]
            # Allow merging compatible group types
            if isinstance(existing, GroupNode) and not is_multigroup:
                return existing
            elif isinstance(existing, MultiGroupNode) and is_multigroup:
                return existing
            else:
                raise HierarchyError(
                    f"Cannot add group '{group_name}' at '{path}': "
                    f"name conflicts with existing {existing.__class__.__name__}")
        
        if is_multigroup:
            group = MultiGroupNode(group_name, parent)
        else:
            group = GroupNode(group_name, parent)
            
        parent.add_child(group)
        self._invalidate_cache()
        return group
        
    def resolve_path(self, path):
        """Resolve a path to a node or list of nodes (for globs)."""
        if path in self._path_cache:
            return self._path_cache[path]
            
        # Handle glob patterns
        if '*' in path or '?' in path:
            result = self._resolve_glob(path)
        else:
            result = self._resolve_single_path(path)
            
        self._path_cache[path] = result
        return result
        
    def _resolve_single_path(self, path):
        """Resolve a single path (no globs)."""
        parts = self._parse_path(path)
        current = self.root
        
        for part in parts:
            if part not in current.children:
                raise PathError(f"Path '{path}' not found: no '{part}' in '{current.get_path()}'")
            current = current.children[part]
            
        return current
        
    def _resolve_glob(self, pattern):
        """Resolve a glob pattern to a list of matching nodes."""
        results = []
        
        # Handle recursive glob **
        if '**' in pattern:
            results.extend(self._resolve_recursive_glob(pattern))
        else:
            results.extend(self._resolve_simple_glob(pattern))
            
        return results
        
    def _resolve_simple_glob(self, pattern):
        """Resolve a simple glob pattern (no recursive **)."""
        parts = self._parse_path(pattern)
        return self._match_path_parts(self.root, parts, 0)
        
    def _resolve_recursive_glob(self, pattern):
        """Resolve a recursive glob pattern with **."""
        # Split on ** to handle each part
        parts = pattern.split('**')
        if len(parts) != 2:
            raise PathError(f"Invalid recursive glob pattern: '{pattern}'")
            
        prefix, suffix = parts
        results = []
        
        # Find all nodes matching the prefix
        if prefix:
            prefix_parts = self._parse_path(prefix.rstrip('.'))
            prefix_nodes = self._match_path_parts(self.root, prefix_parts, 0)
        else:
            prefix_nodes = [self.root]
            
        # For each prefix node, find all descendants matching suffix
        for prefix_node in prefix_nodes:
            if suffix:
                suffix_pattern = suffix.lstrip('.')
                for descendant in prefix_node.iter_descendants():
                    # Match against just the node name, not the full path
                    if self._matches_pattern(descendant.name, suffix_pattern):
                        results.append(descendant)
            else:
                # No suffix, return all descendants
                results.extend(prefix_node.iter_descendants())
                
        return results
        
    def _match_path_parts(self, node, parts, index):
        """Recursively match path parts against the tree."""
        if index >= len(parts):
            return [node]
            
        part = parts[index]
        results = []
        
        if '*' in part or '?' in part:
            # Glob pattern in this part
            for child_name, child in node.children.items():
                if fnmatch.fnmatch(child_name, part):
                    results.extend(self._match_path_parts(child, parts, index + 1))
        else:
            # Literal part
            if part in node.children:
                results.extend(self._match_path_parts(node.children[part], parts, index + 1))
                
        return results
        
    def _matches_pattern(self, path, pattern):
        """Check if a path matches a glob pattern."""
        return fnmatch.fnmatch(path, pattern)
        
    def _parse_path(self, path):
        """Parse a path into components."""
        if not path or path == '/':
            return []
        path = path.strip('./')
        if not path:
            return []
        return path.split('.')
        
    def _ensure_path_exists(self, parts):
        """Ensure all path components exist, creating MultiGroups as needed."""
        current = self.root
        
        for part in parts:
            if part not in current.children:
                # Create MultiGroup for intermediate path components
                multigroup = MultiGroupNode(part, current)
                current.add_child(multigroup)
            current = current.children[part]
            
        return current
        
    def _invalidate_cache(self):
        """Invalidate the path resolution cache."""
        self._path_cache = {}
        
    def detect_cycles(self):
        """Detect cycles in the hierarchy."""
        visited = set()
        rec_stack = set()
        
        def dfs(node):
            node_id = id(node)
            if node_id in rec_stack:
                return True  # Cycle detected
            if node_id in visited:
                return False
                
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for child in node.children.values():
                if dfs(child):
                    return True
                    
            rec_stack.remove(node_id)
            return False
            
        if dfs(self.root):
            raise CycleError("Cycle detected in hierarchy")
            
    def get_hierarchy_dict(self):
        """Get the hierarchy as a dictionary for JSON serialization."""
        def node_to_dict(node):
            result = {
                'name': node.name,
                'type': node.__class__.__name__,
                'path': node.get_path(),
                'children': {}
            }
            
            if isinstance(node, ProgramNode):
                result['state'] = getattr(node.process_config, 'state', 'UNKNOWN')
                
            for child_name, child in node.children.items():
                result['children'][child_name] = node_to_dict(child)
                
            return result
            
        return node_to_dict(self.root)


def split_namespec(namespec):
    """Split a namespec into group path and program name.
    
    Returns (group_path, program_name) or (None, program_name) if no group.
    Supports hierarchical paths like 'frontend.web:nginx'.
    """
    if ':' in namespec:
        group_path, program_name = namespec.rsplit(':', 1)
        return group_path, program_name
    else:
        return None, namespec


def make_namespec(group_path, program_name):
    """Create a namespec from group path and program name."""
    if group_path:
        return f"{group_path}:{program_name}"
    else:
        return program_name
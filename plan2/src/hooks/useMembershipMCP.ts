import { useState, useEffect, useCallback } from 'react';
import { MembershipEntity } from '../types/workflow';

interface OrgContext {
  departments: MembershipEntity[];
  roles: MembershipEntity[];
  members: MembershipEntity[];
}

interface UseMembershipMCPReturn {
  orgContext: OrgContext | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch organizational context from Membership MCP service.
 *
 * Retrieves departments, roles, and members from the backend Membership service
 * for use in form/workflow generation and element configuration.
 *
 * Usage:
 * ```typescript
 * const { orgContext, loading, error } = useMembershipMCP();
 *
 * if (loading) return <div>Loading...</div>;
 * if (error) return <div>Error: {error}</div>;
 *
 * // Use orgContext.departments, orgContext.roles, orgContext.members
 * ```
 *
 * @returns Object with orgContext, loading, error, and refetch function
 */
export const useMembershipMCP = (): UseMembershipMCPReturn => {
  const [orgContext, setOrgContext] = useState<OrgContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOrgStructure = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch('/api/design/org-structure', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch org structure: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        const fetchedContext: OrgContext = {
          departments: data.data.departments || [],
          roles: data.data.roles || [],
          members: data.data.members || [],
        };
        setOrgContext(fetchedContext);
      } else {
        setError('Failed to fetch organization structure');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error occurred';
      setError(errorMessage);
      console.error('Error fetching org structure:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch org structure on mount
  useEffect(() => {
    fetchOrgStructure();
  }, [fetchOrgStructure]);

  return {
    orgContext,
    loading,
    error,
    refetch: fetchOrgStructure,
  };
};

export default useMembershipMCP;

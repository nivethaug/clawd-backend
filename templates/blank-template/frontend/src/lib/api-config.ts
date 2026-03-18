/**
 * API Configuration
 * 
 * Central place for all API endpoint URLs.
 * Base URL is a placeholder that gets replaced during infrastructure provisioning.
 */

// Base URL placeholder - replaced during deployment
// Format: {domain}.dreambigwithai.com → actual domain (e.g., myproject-abc123.dreambigwithai.com)
const API_BASE_URL = "https://{domain}-api.dreambigwithai.com";

/**
 * API Endpoints
 * All backend endpoints are defined here for easy maintenance
 */
export const API_ENDPOINTS = {
  // Health check
  health: "/health",
  
  // Authentication
  auth: {
    register: "/api/auth/register",
    login: "/api/auth/login",
    logout: "/api/auth/logout",
    me: "/api/auth/me",
    refresh: "/api/auth/refresh",
  },
  
  // User
  users: {
    base: "/api/users",
    profile: "/api/users/profile",
    byId: (id: string | number) => `/api/users/${id}`,
  },
  
  // Sessions (example - customize based on your backend)
  sessions: {
    base: "/api/sessions",
    byId: (id: string | number) => `/api/sessions/${id}`,
  },
  
  // Generic CRUD endpoints
  crud: (resource: string) => ({
    list: `/api/${resource}`,
    byId: (id: string | number) => `/api/${resource}/${id}`,
    create: `/api/${resource}`,
    update: (id: string | number) => `/api/${resource}/${id}`,
    delete: (id: string | number) => `/api/${resource}/${id}`,
  }),
} as const;

/**
 * Get full API URL for an endpoint
 * @param endpoint - API endpoint path
 * @returns Full URL with base URL
 */
export function getApiUrl(endpoint: string): string {
  return `${API_BASE_URL}${endpoint}`;
}

/**
 * API Configuration object
 */
export const apiConfig = {
  baseUrl: API_BASE_URL,
  endpoints: API_ENDPOINTS,
  getApiUrl,
  
  // Default headers for API requests
  defaultHeaders: {
    "Content-Type": "application/json",
  },
  
  // Timeout in milliseconds
  timeout: 30000,
  
  // Whether to include credentials (cookies) in requests
  withCredentials: true,
} as const;

export default apiConfig;

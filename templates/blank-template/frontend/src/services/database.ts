/**
 * Database Service
 * 
 * Service layer for communicating with backend API.
 * Uses api-config for endpoint URLs.
 */

import { apiConfig, getApiUrl } from "@/lib/api-config";

// Types
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

export interface QueryParams {
  [key: string]: string | number | boolean | undefined;
}

/**
 * Generic API request helper
 */
async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = getApiUrl(endpoint);
  
  const defaultHeaders: HeadersInit = {
    ...apiConfig.defaultHeaders,
  };
  
  // Add auth token if available (from localStorage)
  const token = localStorage.getItem("auth_token");
  if (token) {
    defaultHeaders["Authorization"] = `Bearer ${token}`;
  }
  
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
      credentials: apiConfig.withCredentials ? "include" : "same-origin",
      signal: AbortSignal.timeout(apiConfig.timeout),
    });
    
    // Handle non-JSON responses
    const contentType = response.headers.get("content-type");
    if (!contentType?.includes("application/json")) {
      if (!response.ok) {
        return {
          success: false,
          error: `HTTP ${response.status}: ${response.statusText}`,
        };
      }
      return { success: true };
    }
    
    const data = await response.json();
    
    if (!response.ok) {
      return {
        success: false,
        error: data.detail || data.error || `HTTP ${response.status}`,
        ...data,
      };
    }
    
    return {
      success: true,
      data,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return {
      success: false,
      error: message,
    };
  }
}

/**
 * HTTP Methods
 */
export const api = {
  get: <T>(endpoint: string, params?: QueryParams) => {
    let url = endpoint;
    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined) {
          searchParams.append(key, String(value));
        }
      });
      url += `?${searchParams.toString()}`;
    }
    return apiRequest<T>(url, { method: "GET" });
  },
  
  post: <T>(endpoint: string, body?: unknown) => {
    return apiRequest<T>(endpoint, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  },
  
  put: <T>(endpoint: string, body?: unknown) => {
    return apiRequest<T>(endpoint, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    });
  },
  
  patch: <T>(endpoint: string, body?: unknown) => {
    return apiRequest<T>(endpoint, {
      method: "PATCH",
      body: body ? JSON.stringify(body) : undefined,
    });
  },
  
  delete: <T>(endpoint: string) => {
    return apiRequest<T>(endpoint, { method: "DELETE" });
  },
};

/**
 * Health Check Service
 */
export const healthService = {
  check: () => api.get<{ status: string }>(apiConfig.endpoints.health),
};

/**
 * Auth Service
 */
export const authService = {
  register: (email: string, password: string, name?: string) =>
    api.post(apiConfig.endpoints.auth.register, { email, password, name }),
  
  login: (email: string, password: string) =>
    api.post<{ token: string; user: User }>(apiConfig.endpoints.auth.login, { email, password }),
  
  logout: () => api.post(apiConfig.endpoints.auth.logout),
  
  me: () => api.get<User>(apiConfig.endpoints.auth.me),
  
  refresh: () => api.post<{ token: string }>(apiConfig.endpoints.auth.refresh),
};

/**
 * User Service
 */
export const userService = {
  getProfile: () => api.get<User>(apiConfig.endpoints.users.profile),
  
  updateProfile: (data: Partial<User>) =>
    api.patch<User>(apiConfig.endpoints.users.profile, data),
  
  getById: (id: string | number) =>
    api.get<User>(apiConfig.endpoints.users.byId(id)),
  
  list: (params?: QueryParams) =>
    api.get<PaginatedResponse<User>>(apiConfig.endpoints.users.base, params),
};

/**
 * Generic CRUD Service Factory
 * Creates a service with standard CRUD operations for any resource
 */
export function createCrudService<T>(resource: string) {
  const endpoints = apiConfig.endpoints.crud(resource);
  
  return {
    list: (params?: QueryParams) =>
      api.get<PaginatedResponse<T>>(endpoints.list, params),
    
    getById: (id: string | number) =>
      api.get<T>(endpoints.byId(id)),
    
    create: (data: Partial<T>) =>
      api.post<T>(endpoints.create, data),
    
    update: (id: string | number, data: Partial<T>) =>
      api.put<T>(endpoints.update(id), data),
    
    delete: (id: string | number) =>
      api.delete(endpoints.delete(id)),
  };
}

/**
 * User type (customize based on your backend)
 */
export interface User {
  id: number;
  email: string;
  name?: string;
  created_at: string;
  updated_at?: string;
}

// Export all services
export default {
  api,
  healthService,
  authService,
  userService,
  createCrudService,
};

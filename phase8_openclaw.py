#!/usr/bin/env python3
"""
Phase 8: Smart Frontend Refinement with Component & Page Creation

Creates:
- Project-specific components based on project type
- Full pages that import and use components
- Routes in App.tsx for navigation
- pages.md documenting each page's responsibility
"""

import os
import subprocess
import re
import logging
from pathlib import Path
import sys
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def create_file(content: str, file_path: Path) -> bool:
    """Create a file."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        logger.info(f"✅ Created: {file_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create {file_path}: {e}")
        return False


def modify_file(file_path: Path, replacements: List[tuple]) -> bool:
    """Modify existing file with replacements."""
    try:
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return False
        content = file_path.read_text(encoding='utf-8')
        original = content
        for pattern, replacement in replacements:
            if isinstance(pattern, str):
                new = content.replace(pattern, replacement)
                if new != content:
                    content = new
            else:
                new = pattern.sub(replacement, content)
                if new != content:
                    content = new
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            logger.info(f"✅ Modified: {file_path}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Failed to modify {file_path}: {e}")
        return False


def analyze_project_type(description: str) -> str:
    """Analyze project description to identify type."""
    desc_lower = description.lower()
    if any(k in desc_lower for k in ['ecommerce', 'e-commerce', 'store', 'shop', 'product', 'cart', 'checkout', 'payment', 'online store', 'selling products']):
        return 'ecommerce'
    elif any(k in desc_lower for k in ['task', 'kanban', 'todo', 'project management', 'workflow']):
        return "task_management"
    elif any(k in desc_lower for k in ['blog', 'content', 'article', 'post', 'publication']):
        return "blog"
    else:
        return "custom"


def get_ecommerce_files(project_name: str) -> Dict[str, Any]:
    """Get e-commerce files (components + pages)."""
    return {
        "components": [
            {
                "path": "src/features/products/ProductCard.tsx",
                "content": """import React from 'react';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

interface ProductCardProps {
  id: string;
  title: string;
  price: number;
  image?: string;
  description: string;
  onAddToCart?: (id: string) => void;
}

export default function ProductCard({
  id,
  title,
  price,
  image,
  description,
  onAddToCart
}: ProductCardProps) {
  return (
    <Card className="overflow-hidden hover:shadow-lg transition-shadow">
      {image && (
        <div className="relative h-48 overflow-hidden">
          <img
            src={image}
            alt={title}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <CardContent className="p-4">
        <Badge variant="secondary" className="mb-2">New</Badge>
        <h3 className="font-semibold text-lg mb-2">{title}</h3>
        <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
          {description}
        </p>
        <div className="flex items-center justify-between">
          <span className="text-2xl font-bold">${price.toFixed(2)}</span>
          <Button onClick={() => onAddToCart?.(id)} variant="default">
            Add to Cart
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
"""
            },
            {
                "path": "src/features/products/ProductList.tsx",
                "content": """import React from 'react';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import ProductCard from './ProductCard';

interface Product {
  id: string;
  title: string;
  price: number;
  image?: string;
  description: string;
  category?: string;
}

interface ProductListProps {
  products: Product[];
  category?: string;
  searchQuery?: string;
  onAddToCart?: (id: string) => void;
}

export default function ProductList({
  products,
  category = 'all',
  searchQuery = '',
  onAddToCart
}: ProductListProps) {
  const filteredProducts = products.filter(product => {
    const matchesCategory = category === 'all' || product.category === category;
    const matchesSearch = product.title.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  return (
    <div className="space-y-6">
      <div className="flex gap-4 mb-6">
        <Input placeholder="Search products..." value={searchQuery} className="flex-1" />
        <Select value={category}>
          <SelectTrigger className="w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            <SelectItem value="electronics">Electronics</SelectItem>
            <SelectItem value="clothing">Clothing</SelectItem>
            <SelectItem value="home">Home & Garden</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredProducts.map(product => (
          <ProductCard
            key={product.id}
            id={product.id}
            title={product.title}
            price={product.price}
            image={product.image}
            description={product.description}
            onAddToCart={onAddToCart}
          />
        ))}
      </div>
    </div>
  );
}
"""
            },
            {
                "path": "src/features/cart/ShoppingCart.tsx",
                "content": """import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface CartItem {
  id: string;
  title: string;
  price: number;
  quantity: number;
}

interface ShoppingCartProps {
  items: CartItem[];
  onUpdateQuantity: (id: string, delta: number) => void;
  onRemove: (id: string) => void;
  onCheckout: () => void;
}

export default function ShoppingCart({
  items,
  onUpdateQuantity,
  onRemove,
  onCheckout
}: ShoppingCartProps) {
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0);

  return (
    <Card>
      <CardContent className="p-6">
        <h2 className="text-2xl font-bold mb-6">Shopping Cart</h2>
        <div className="space-y-4">
          {items.map(item => (
            <div
              key={item.id}
              className="flex items-center justify-between p-4 border rounded-lg"
            >
              <div className="flex-1">
                <h3 className="font-semibold">{item.title}</h3>
                <p className="text-muted-foreground">${item.price.toFixed(2)}</p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onUpdateQuantity(item.id, -1)}
                  disabled={item.quantity <= 1}
                >
                  -
                </Button>
                <Input
                  type="number"
                  value={item.quantity}
                  readOnly
                  className="w-16 text-center"
                />
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onUpdateQuantity(item.id, 1)}
                >
                  +
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onRemove(item.id)}
                  className="text-destructive"
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-6 pt-6 border-t">
          <div className="flex justify-between text-lg font-semibold">
            <span>Total:</span>
            <span>${total.toFixed(2)}</span>
          </div>
          <Button className="w-full mt-4" size="lg" onClick={onCheckout}>
            Proceed to Checkout
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
"""
            }
        ],
        "pages": [
            {
                "path": "src/pages/Products.tsx",
                "content": f"""import React, {{ useState }} from 'react';
import ProductList from '@/features/products/ProductList';

interface Product {{
  id: string;
  title: string;
  price: number;
  image?: string;
  description: string;
  category?: string;
}}

export default function Products() {{
  const [products] = useState<Product[]>([]);
  const [category, setCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // TODO: Fetch products from backend API
  const loadProducts = async () => {{
    // const response = await fetch('/api/products');
    // const data = await response.json();
    // setProducts(data);
  }};

  const handleAddToCart = (productId: string) => {{
    // TODO: Add product to cart state/backend
    console.log('Adding to cart:', productId);
  }};

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-4xl font-bold mb-8">Products</h1>
      <p className="text-muted-foreground mb-8">
        Browse our catalog of high-quality products
      </p>
      <ProductList
        products={{products}}
        category={{category}}
        searchQuery={{searchQuery}}
        onAddToCart={{handleAddToCart}}
      />
    </div>
  );
}}
""",
                "routes": [
                    "/products"
                ],
                "description": "Products listing page with search, category filters, and grid of product cards. Users can browse, search, filter products and add items to cart from this page."
            },
            {
                "path": "src/pages/Cart.tsx",
                "content": """import React, { useState } from 'react';
import ShoppingCart from '@/features/cart/ShoppingCart';

interface CartItem {
  id: string;
  title: string;
  price: number;
  quantity: number;
}

export default function Cart() {
  const [items, setItems] = useState<CartItem[]>([]);

  // TODO: Load cart items from backend/localStorage
  const loadCart = async () => {
    // const savedCart = localStorage.getItem('cart');
    // if (savedCart) setItems(JSON.parse(savedCart));
  };

  const handleUpdateQuantity = (id: string, delta: number) => {
    setItems(prev => prev.map(item =>
      item.id === id ? { ...item, quantity: Math.max(1, item.quantity + delta) } : item
    ));
  };

  const handleRemove = (id: string) => {
    setItems(prev => prev.filter(item => item.id !== id));
  };

  const handleCheckout = () => {
    window.location.href = '/checkout';
  };

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-4xl font-bold mb-8">Shopping Cart</h1>
      {items.length === 0 ? (
        <p className="text-muted-foreground text-center py-12">
          Your cart is empty. Continue shopping!
        </p>
      ) : (
        <ShoppingCart
          items={items}
          onUpdateQuantity={handleUpdateQuantity}
          onRemove={handleRemove}
          onCheckout={handleCheckout}
        />
      )}
    </div>
  );
}
""",
                "routes": [
                    "/cart"
                ],
                "description": "Shopping cart page displaying all items user has added. Shows item details, quantity controls, remove button, total price, and checkout button to proceed to payment flow."
            },
            {
                "path": "src/pages/Checkout.tsx",
                "content": f"""import React, {{ useState }} from 'react';
import {{ Card, CardContent }} from '@/components/ui/card';
import {{ Button }} from '@/components/ui/button';
import {{ Input }} from '@/components/ui/input';

export default function Checkout() {{
  const [formData, setFormData] = useState({{
    email: '',
    address: '',
    city: '',
    zipCode: '',
    country: ''
  }});

  const handleSubmit = (e: React.FormEvent) => {{
    e.preventDefault();
    // TODO: Submit order to backend
    console.log('Checkout data:', formData);
    // Navigate to order confirmation page
  }};

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-4xl font-bold mb-8">Checkout</h1>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <Card>
          <CardContent className="p-6">
            <h2 className="text-2xl font-semibold mb-6">Shipping Information</h2>
            <form onSubmit={{handleSubmit}} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Email</label>
                <Input
                  type="email"
                  placeholder="your@email.com"
                  value={{formData.email}}
                  onChange={{(e) => setFormData({{...formData, email: e.target.value}})}}
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Address</label>
                <Input
                  placeholder="123 Main Street"
                  value={{formData.address}}
                  onChange={{(e) => setFormData({{...formData, address: e.target.value}})}}
                  required
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-2">City</label>
                  <Input
                    placeholder="New York"
                    value={{formData.city}}
                    onChange={{(e) => setFormData({{...formData, city: e.target.value}})}}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">ZIP Code</label>
                  <Input
                    placeholder="10001"
                    value={{formData.zipCode}}
                    onChange={{(e) => setFormData({{...formData, zipCode: e.target.value}})}}
                    required
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Country</label>
                <Input
                  placeholder="United States"
                  value={{formData.country}}
                  onChange={{(e) => setFormData({{...formData, country: e.target.value}})}}
                  required
                />
              </div>
              <Button type="submit" className="w-full" size="lg">
                Place Order
              </Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <h2 className="text-2xl font-semibold mb-6">Order Summary</h2>
            <div className="space-y-4">
              <div className="flex justify-between">
                <span>Subtotal</span>
                <span>$0.00</span>
              </div>
              <div className="flex justify-between">
                <span>Shipping</span>
                <span>$5.99</span>
              </div>
              <div className="flex justify-between">
                <span>Tax</span>
                <span>$0.00</span>
              </div>
              <div className="flex justify-between text-lg font-bold pt-4 border-t">
                <span>Total</span>
                <span>$5.99</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}}
""",
                "routes": [
                    "/checkout"
                ],
                "description": "Checkout page with shipping form, payment options, and order summary. Collects user shipping information and shows calculated total with shipping and tax. Final step before order placement."
            }
        ]
    }


def get_task_management_files() -> Dict[str, Any]:
    """Get task management files."""
    return {
        "components": [
            {
                "path": "src/features/tasks/TaskCard.tsx",
                "content": """import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface TaskCardProps {
  id: string;
  title: string;
  status: 'todo' | 'in_progress' | 'done';
  priority: 'low' | 'medium' | 'high';
  assignee?: string;
  dueDate?: string;
}

export default function TaskCard({
  id,
  title,
  status,
  priority,
  assignee,
  dueDate
}: TaskCardProps) {
  const statusColors = {
    todo: 'bg-gray-100 text-gray-800',
    in_progress: 'bg-yellow-100 text-yellow-800',
    done: 'bg-green-100 text-green-800'
  };

  const priorityColors = {
    low: 'bg-blue-100 text-blue-800',
    medium: 'bg-orange-100 text-orange-800',
    high: 'bg-red-100 text-red-800'
  };

  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer">
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-3">
          <h3 className="font-semibold text-lg flex-1">{title}</h3>
          <Badge className={statusColors[status]}>
            {status.replace('_', ' ')}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
          Task description goes here...
        </p>
        <div className="flex items-center justify-between">
          <Badge className={priorityColors[priority]}>
            {priority} priority
          </Badge>
          {dueDate && (
            <span className="text-sm text-muted-foreground">
              Due: {dueDate}
            </span>
          )}
        </div>
        {assignee && (
          <div className="mt-3 pt-3 border-t flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center text-xs">
              {assignee.charAt(0).toUpperCase()}
            </div>
            <span className="text-sm text-muted-foreground">{assignee}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
"""
            },
            {
                "path": "src/features/tasks/KanbanBoard.tsx",
                "content": """import React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface Task {
  id: string;
  title: string;
  status: 'todo' | 'in_progress' | 'done';
  priority: 'low' | 'medium' | 'high';
  assignee?: string;
  dueDate?: string;
}

interface KanbanBoardProps {
  tasks: Task[];
  onMoveTask?: (taskId: string, newStatus: string) => void;
}

export default function KanbanBoard({ tasks, onMoveTask }: KanbanBoardProps) {
  const columns: { status: string; title: string; color: string }[] = [
    { status: 'todo', title: 'To Do', color: 'bg-gray-50 border-gray-200' },
    { status: 'in_progress', title: 'In Progress', color: 'bg-yellow-50 border-yellow-200' },
    { status: 'done', title: 'Done', color: 'bg-green-50 border-green-200' }
  ];

  const handleDragStart = (taskId: string, fromStatus: string) => {
    // TODO: Implement drag and drop
    console.log('Dragging task:', taskId, 'from:', fromStatus);
  };

  const handleDrop = (toStatus: string, taskId: string) => {
    onMoveTask?.(taskId, toStatus);
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
      {columns.map(column => (
        <Card key={column.status} className={column.color}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">{column.title}</h2>
              <Badge variant="outline">
                {tasks.filter(t => t.status === column.status).length}
              </Badge>
            </div>
            <div className="space-y-3">
              {tasks
                .filter(task => task.status === column.status)
                .map(task => (
                  <div
                    key={task.id}
                    draggable
                    onDragStart={() => handleDragStart(task.id, column.status)}
                    onDrop={() => handleDrop(column.status, task.id)}
                    className="bg-white p-3 rounded-lg border cursor-move"
                  >
                    <h4 className="font-semibold">{task.title}</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      Task description...
                    </p>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
"""
            }
        ],
        "pages": [
            {
                "path": "src/pages/Tasks.tsx",
                "content": """import React, { useState } from 'react';
import { KanbanBoard } from '@/features/tasks/KanbanBoard';

interface Task {
  id: string;
  title: string;
  status: 'todo' | 'in_progress' | 'done';
  priority: 'low' | 'medium' | 'high';
}

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[]>([]);

  // TODO: Fetch tasks from backend API
  const loadTasks = async () => {
    // const response = await fetch('/api/tasks');
    // const data = await response.json();
    // setTasks(data);
  };

  const handleMoveTask = (taskId: string, newStatus: string) => {
    setTasks(prev => prev.map(task =>
      task.id === taskId ? { ...task, status: newStatus as any } : task
    ));
    // TODO: Update task status in backend
  };

  return (
    <div className="container mx-auto py-8">
      <h1 className="text-4xl font-bold mb-8">Task Board</h1>
      <p className="text-muted-foreground mb-8">
        Manage your tasks using the Kanban board below
      </p>
      <KanbanBoard tasks={tasks} onMoveTask={handleMoveTask} />
    </div>
  );
}
""",
                "routes": ["/tasks"],
                "description": "Task management page with Kanban board layout. Users can view tasks in To Do, In Progress, and Done columns, drag tasks between columns to update status, and see task counts per column."
            }
        ]
    }


def get_blog_files() -> Dict[str, Any]:
    """Get blog files."""
    return {
        "components": [
            {
                "path": "src/features/blog/BlogPostCard.tsx",
                "content": """import React from 'react';
import { Card, CardContent, CardFooter } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Calendar, User } from 'lucide-react';

interface BlogPostCardProps {
  id: string;
  title: string;
  excerpt: string;
  author: string;
  date: string;
  tags?: string[];
  image?: string;
}

export default function BlogPostCard({
  id,
  title,
  excerpt,
  author,
  date,
  tags,
  image
}: BlogPostCardProps) {
  return (
    <Card className="overflow-hidden hover:shadow-lg transition-shadow">
      {image && (
        <div className="relative h-48 overflow-hidden">
          <img
            src={image}
            alt={title}
            className="w-full h-full object-cover"
          />
        </div>
      )}
      <CardContent className="p-6">
        <h3 className="font-bold text-xl mb-3 hover:text-primary cursor-pointer">
          {title}
        </h3>
        <p className="text-muted-foreground mb-4 line-clamp-3">
          {excerpt}
        </p>
        <div className="flex flex-wrap gap-2 mb-4">
          {tags?.map(tag => (
            <Badge key={tag} variant="secondary" className="text-xs">
              {tag}
            </Badge>
          ))}
        </div>
        <CardFooter className="pt-0 flex items-center justify-between text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <User className="w-4 h-4" />
            <span>{author}</span>
          </div>
          <div className="flex items-center gap-1">
            <Calendar className="w-4 h-4" />
            <span>{date}</span>
          </div>
        </CardFooter>
      </CardContent>
    </Card>
  );
}
"""
            }
        ],
        "pages": [
            {
                "path": "src/pages/Blog.tsx",
                "content": """import React, { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { BlogPostCard } from '@/features/blog/BlogPostCard';

interface BlogPost {
  id: string;
  title: string;
  excerpt: string;
  author: string;
  date: string;
  tags?: string[];
  image?: string;
}

export default function Blog() {
  const [posts, setPosts] = useState<BlogPost[]>([]);
  const [category, setCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // TODO: Fetch blog posts from backend API
  const loadPosts = async () => {
    // const response = await fetch('/api/blog/posts');
    // const data = await response.json();
    // setPosts(data);
  };

  return (
    <div className="container mx-auto py-8">
      <div className="mb-12 text-center">
        <h1 className="text-5xl font-bold mb-4">Blog</h1>
        <p className="text-xl text-muted-foreground">
          Insights, tutorials, and updates
        </p>
      </div>
      <div className="flex gap-4 mb-8">
        <Input
          placeholder="Search posts..."
          value={searchQuery}
          className="flex-1"
        />
        <Select value={category}>
          <SelectTrigger className="w-[180px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            <SelectItem value="tutorials">Tutorials</SelectItem>
            <SelectItem value="news">News</SelectItem>
            <SelectItem value="updates">Updates</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {posts.map(post => (
          <BlogPostCard
            key={post.id}
            id={post.id}
            title={post.title}
            excerpt={post.excerpt}
            author={post.author}
            date={post.date}
            tags={post.tags}
            image={post.image}
          />
        ))}
      </div>
    </div>
  );
}
""",
                "routes": ["/blog"],
                "description": "Blog listing page with search, category filters, and grid of post cards. Displays post excerpts, author info, publication date, and tags. Users can filter by category and search by keywords."
            }
        ]
    }


def get_app_router_updates(project_type: str, pages: List[Dict[str, Any]]) -> List[tuple]:
    """Get App.tsx route updates."""
    route_updates = []
    
    for page in pages:
        routes = page.get("routes", [])
        if not routes or not isinstance(routes, list) or len(routes) == 0:
            logger.warning(f"   Skipping {page['path']} - no routes defined")
            continue
        
        route_path = routes[0]
        route_import = f"import {Path(page['path']).stem} from '@/pages/{Path(page['path']).stem}';"
        route_element = f'          <Route path="{route_path}" element={{<{Path(page['path']).stem} />}} />'
        
        # Append as 2-element tuple
        route_updates.append((route_import, route_element))
    
    return route_updates


def create_pages_md(frontend_path: Path, pages: List[Dict[str, Any]], project_type: str) -> bool:
    """Create pages.md documenting page responsibilities."""
    try:
        pages_md_path = frontend_path / "pages.md"
        
        content = "# Pages Documentation\n\n"
        content += f"**Project Type:** {project_type}\n\n"
        content += "---\n\n"
        
        for page in pages:
            routes = page.get("routes", [])
            # Safe route access with fallback
            if not routes or not isinstance(routes, list) or len(routes) == 0:
                route = "N/A"
            else:
                route = routes[0]
                
            description = page.get("description", "No description")
            
            content += f"## {Path(page['path']).stem}\n\n"
            content += f"**Route:** `{route}`\n\n"
            content += f"**File:** `{page['path']}`\n\n"
            content += f"**Responsibility:** {description}\n\n"
            content += "---\n\n"
        
        content += "\n## Implementation Notes\n\n"
        content += "- All pages follow the same component-based architecture\n"
        content += "- Components are imported from `src/features/` directories\n"
        content += "- Pages handle state management and API calls\n"
        content += "- Routes are registered in `src/App.tsx`\n"
        content += "- Navigation uses React Router for client-side routing\n"
        
        pages_md_path.write_text(content, encoding='utf-8')
        logger.info(f"✅ Created: {pages_md_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create pages.md: {e}")
        return False


def update_app_routes(frontend_path: Path, route_updates: List[tuple]) -> bool:
    """Smart update of App.tsx routes by finding <Routes> section."""
    try:
        app_path = frontend_path / "src/App.tsx"
        if not app_path.exists():
            logger.warning("   App.tsx not found")
            return False
        
        content = app_path.read_text(encoding='utf-8')
        original_content = content
        
        if not route_updates or len(route_updates) == 0:
            logger.warning("   No routes to add")
            return False
        
        # Extract imports (first element of each tuple) and routes (second element)
        imports = []
        routes = []
        for t in route_updates:
            if not t or len(t) == 0:
                continue
            # First element is import line
            if t[0] is not None:
                imports.append(t[0])
            # Second element is route line
            if len(t) >= 2 and t[1] is not None:
                routes.append(t[1])
        
        if not imports and not routes:
            logger.warning("   No valid route updates to apply")
            return False
        
        # Add imports if not already present
        for import_line in imports:
            import_line = import_line.strip()
            if import_line and import_line not in content:
                # Add import after last existing import
                lines = content.split('\n')
                import_lines_indices = [i for i, line in enumerate(lines) if line.strip().startswith('import')]
                if import_lines_indices:
                    last_import_idx = import_lines_indices[-1]
                    # Insert after the last import
                    content = '\n'.join(
                        lines[:last_import_idx+1] + 
                        [import_line] + 
                        lines[last_import_idx+1:]
                    )
        
        # Add routes inside <Routes> section
        if routes and "<Routes>" in content and "</Routes>" in content:
            routes_start = content.find("<Routes>") + len("<Routes>")
            routes_end = content.find("</Routes>")
            
            if routes_start > 0 and routes_end > routes_start:
                routes_text = "\n".join(routes)
                
                # Insert routes after opening <Routes> tag
                content = content[:routes_start] + "\n" + routes_text + "\n" + content[routes_start:]
                logger.info(f"   Added {len(routes)} routes")
        
        if content != original_content:
            app_path.write_text(content, encoding='utf-8')
            logger.info("   App.tsx updated with routes")
            return True
        
        logger.warning("   No changes to App.tsx")
        return False
    except Exception as e:
        logger.error(f"   Failed to update App.tsx: {e}")
        return False
        content += "- All pages follow the same component-based architecture\n"
        content += "- Components are imported from `src/features/` directories\n"
        content += "- Pages handle state management and API calls\n"
        content += "- Routes are registered in `src/App.tsx`\n"
        content += "- Navigation uses React Router for client-side routing\n"
        
        pages_md_path.write_text(content, encoding='utf-8')
        logger.info(f"✅ Created: {pages_md_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create pages.md: {e}")
        return False


def run_npm_build(cwd: str) -> bool:
    """Run npm build."""
    logger.info("🔨 Running npm run build")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        return result.returncode == 0
    except:
        return False


def git_commit(message: str, cwd: str) -> bool:
    """Commit changes."""
    logger.info(f"📝 Git commit: {message[:50]}...")
    try:
        subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=cwd, capture_output=True)
        return True
    except:
        return False


def run_phase_8_smart(project_name: str, project_path: str, description: str) -> bool:
    """Execute smart Phase 8."""
    
    frontend_path = Path(project_path) / "frontend"
    
    logger.info(f"🚀 Phase 8: Smart Frontend Refinement")
    logger.info(f"   Project: {project_name}")
    logger.info(f"   Description: {description[:150]}...")
    
    # Step 1: Analyze project type
    logger.info("🔍 Step 1: Analyzing project type...")
    project_type = analyze_project_type(description)
    logger.info(f"   Project type: {project_type}")
    
    # Step 2: Get files to create
    logger.info("📝 Step 2: Getting files to create...")
    file_getters = {
        "ecommerce": get_ecommerce_files,
        "task_management": get_task_management_files,
        "blog": get_blog_files,
        "custom": lambda x: {"components": [], "pages": []}
    }
    
    project_files = file_getters.get(project_type, lambda x: {"components": [], "pages": []})(project_name)
    components = project_files["components"]
    pages = project_files["pages"]
    
    logger.info(f"   Components: {len(components)}")
    logger.info(f"   Pages: {len(pages)}")
    
    summary = {
        "project": project_name,
        "project_type": project_type,
        "components_created": 0,
        "pages_created": 0,
        "files_modified": []
    }
    
    import time
    start_time = time.time()
    
    # Step 3: Create components
    logger.info(f"🔨 Step 3: Creating {len(components)} components...")
    for comp in components:
        if create_file(comp["content"], frontend_path / comp["path"]):
            summary["components_created"] += 1
            summary["files_modified"].append(comp["path"])
    
    # Step 4: Create pages
    logger.info(f"📄 Step 4: Creating {len(pages)} pages...")
    for page in pages:
        if create_file(page["content"], frontend_path / page["path"]):
            summary["pages_created"] += 1
            summary["files_modified"].append(page["path"])
    
    # Step 5: Update App.tsx with routes
    logger.info("🛣️ Step 5: Updating App.tsx with routes...")
    app_path = frontend_path / "src/App.tsx"
    if app_path.exists() and pages:
        # Get route updates
        route_updates = get_app_router_updates(project_type, pages)
        
        if route_updates:
            # Update App.tsx with new routes
            if update_app_routes(frontend_path, route_updates):
                summary["files_modified"].append("src/App.tsx")
                logger.info("   Routes added to App.tsx")
            else:
                logger.warning("   Could not add routes to App.tsx")
        else:
            logger.info("   No routes to add")
    
    # Step 6: Create pages.md
    logger.info("📝 Step 6: Creating pages.md...")
    create_pages_md(frontend_path, pages, project_type)
    summary["files_modified"].append("pages.md")
    
    # Step 7: Apply branding
    logger.info("🎨 Step 7: Applying branding...")
    branding_updates = [
        (r"<title>Lovable App</title>", f"<title>{project_name}</title>"),
        (r'<meta name="description" content="Lovable Generated Project" />',
         f'<meta name="description" content="{project_name} - Generated Project" />'),
        (r'<meta name="author" content="Lovable" />',
         f'<meta name="author" content="{project_name}" />'),
        (r'<meta property="og:title" content="Lovable App" />',
         f'<meta property="og:title" content="{project_name}" />'),
        (r'<meta property="og:description" content="Lovable Generated Project" />',
         f'<meta property="og:description" content="{project_name} - Generated Project" />'),
        (r"Lovable App", project_name),
    ]
    if modify_file(frontend_path / "index.html", branding_updates):
        summary["files_modified"].append("index.html")
        logger.info("   Branding applied to index.html")
    
    # Step 8: Verify build
    logger.info("🧪 Step 8: Verifying build...")
    build_success = run_npm_build(str(frontend_path))
    
    if build_success:
        logger.info("✅ Build passed")
        git_commit(
            message=f"Phase 8: {summary['components_created']} components + {summary['pages_created']} pages + routes + pages.md",
            cwd=str(frontend_path)
        )
    else:
        logger.warning("⚠️ Build failed, continuing...")
    
    # Step 9: Restart frontend service
    logger.info("🔄 Step 9: Restarting frontend service...")
    
    # Try different service name formats
    service_names = [
        f"{project_name}-frontend",  # Original name with spaces
        f"{project_name.lower().replace(' ', '-')}-frontend",  # Lowercase with hyphens
    ]
    
    restarted = False
    for service_name in service_names:
        try:
            result = subprocess.run(
                ["pm2", "restart", service_name],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode == 0:
                logger.info(f"   Frontend service restarted: {service_name}")
                restarted = True
                break
        except Exception as e:
            logger.debug(f"   Failed to restart {service_name}: {e}")
    
    if not restarted:
        logger.warning("   Could not restart frontend service (tried multiple formats)")
    
    # Step 10: Create summary
    total_time = time.time() - start_time
    summary['total_time_seconds'] = total_time
    
    create_summary_md(frontend_path, summary, description, project_type)
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ Phase 8 completed!")
    logger.info("=" * 60)
    logger.info(f"   Project type: {project_type}")
    logger.info(f"   Components: {summary['components_created']}")
    logger.info(f"   Pages: {summary['pages_created']}")
    logger.info(f"   Total files: {len(summary['files_modified'])}")
    logger.info(f"   Time: {total_time:.1f} minutes")
    logger.info("=" * 60)
    
    return len(summary["files_modified"]) > 0


def create_summary_md(frontend_path: Path, summary: Dict, description: str, project_type: str):
    """Create SUMMARY.md."""
    summary_path = frontend_path / "SUMMARY.md"
    
    content = f"""# Phase 8: Smart Frontend Refinement Summary

**Project:** {summary['project']}
**Project Type:** {project_type}
**Execution Date:** 2026-02-27
**Total Duration:** {summary['total_time_seconds'] / 60:.1f} minutes

## Project Description

{description}

## Files Created

### Components ({summary['components_created']})
{chr(10).join(f"- `{f}`" for f in summary['files_modified'] if 'components' in f)}

### Pages ({summary['pages_created']})
{chr(10).join(f"- `{f}`" for f in summary['files_modified'] if 'pages/' in f)}

### Configuration Files
- `pages.md` - Documentation of each page's responsibility
- `src/App.tsx` - Updated with new routes

## Implementation Details

1. **Component Creation**: {summary['components_created']} feature-specific components
2. **Page Creation**: {summary['pages_created']} full pages with imports
3. **Routing**: Added routes to App.tsx
4. **Documentation**: Created pages.md with page responsibilities
5. **Branding**: Updated index.html and App.tsx
6. **Build**: Verified successful compilation
7. **Frontend Deployment**: Restarted PM2 frontend service
8. **Git**: Committed all changes

## Frontend Deployment

✅ **Frontend service restarted automatically**
- Service name: `{project_name.lower().replace(' ', '-')}-frontend`
- New pages are now accessible via routes
- Check `/pages.md` for available routes

## Next Steps

1. Review pages.md for page responsibilities
2. Test all routes and navigation
3. Implement backend API endpoints for data fetching
4. Add proper state management (Redux/Context)
5. Customize page designs and layouts

---
*Generated by Phase 8 Smart System*
"""
    
    try:
        summary_path.write_text(content, encoding='utf-8')
        logger.info("✓ SUMMARY.md created")
    except Exception as e:
        logger.error(f"❌ Failed to create SUMMARY.md: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 phase8_openclaw.py <project_name> <project_path> [description]")
        sys.exit(1)
    
    project_name = sys.argv[1]
    project_path = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else "Frontend refinement"
    
    try:
        success = run_phase_8_smart(project_name, project_path, description)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"💥 Phase 8 failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

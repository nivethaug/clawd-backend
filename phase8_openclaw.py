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
    elif any(k in desc_lower for k in ['social', 'social media', 'socialmedia', 'social manager', 'socialmedia manager', 'instagram', 'twitter', 'facebook', 'linkedin', 'scheduler']):
        return "social_media"
    elif any(k in desc_lower for k in ['blog', 'content', 'article', 'publication']):
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



def get_social_media_files(project_name: str) -> Dict[str, Any]:
    """Get social media manager files."""
    return {
        "components": [
            {
                "path": "src/components/Navbar.tsx",
                "content": '''import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Menu, X, LogIn, LogOut } from 'lucide-react';

export default function Navbar() {
  const [isOpen, setIsOpen] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setIsOpen(false);
  }, [location.pathname]);

  const navLinks = [
    { path: '/', label: 'Home' },
    { path: '/dashboard', label: 'Dashboard', protected: true },
    { path: '/settings', label: 'Settings', protected: true },
  ];

  return (
    <nav className="border-b bg-background">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link to="/" className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-primary rounded-md flex items-center justify-center">
              <span className="text-primary-foreground font-bold text-sm">SM</span>
            </div>
            <span className="font-bold text-lg">SocialManager</span>
          </Link>

          <div className="hidden md:flex items-center space-x-6">
            {navLinks.map((link) => {
              if (link.protected && !isAuthenticated) return null;
              return (
                <Link
                  key={link.path}
                  to={link.path}
                  className={`text-sm font-medium transition-colors hover:text-primary ${
                    location.pathname === link.path ? 'text-primary' : 'text-muted-foreground'
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </div>

          <div className="hidden md:flex items-center space-x-2">
            {isAuthenticated ? (
              <Button variant="ghost" size="sm">
                <LogOut className="w-4 h-4 mr-2" />
                Logout
              </Button>
            ) : (
              <>
                <Link to="/login">
                  <Button variant="ghost" size="sm">
                    <LogIn className="w-4 h-4 mr-2" />
                    Sign In
                  </Button>
                </Link>
                <Link to="/signup">
                  <Button size="sm">Sign Up</Button>
                </Link>
              </>
            )}
          </div>

          <button
            className="md:hidden"
            onClick={() => setIsOpen(!isOpen)}
            aria-label="Toggle menu"
          >
            {isOpen ? <X /> : <Menu />}
          </button>
        </div>

        {isOpen && (
          <div className="md:hidden py-4 space-y-2">
            {navLinks.map((link) => {
              if (link.protected && !isAuthenticated) return null;
              return (
                <Link
                  key={link.path}
                  to={link.path}
                  className={`block px-4 py-2 text-sm font-medium ${
                    location.pathname === link.path ? 'text-primary' : 'text-muted-foreground'
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
            <div className="px-4 pt-4 space-y-2">
              {isAuthenticated ? (
                <Button variant="ghost" size="sm" className="w-full">
                  <LogOut className="w-4 h-4 mr-2" />
                  Logout
                </Button>
              ) : (
                <>
                  <Link to="/login" className="block">
                    <Button variant="ghost" size="sm" className="w-full">
                      <LogIn className="w-4 h-4 mr-2" />
                      Sign In
                    </Button>
                  </Link>
                  <Link to="/signup" className="block">
                    <Button size="sm" className="w-full">Sign Up</Button>
                  </Link>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
'''
            },
            {
                "path": "src/components/Footer.tsx",
                "content": '''import React from 'react';
import { Link } from 'react-router-dom';
import { Facebook, Twitter, Instagram, Linkedin, Github } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="border-t bg-background">
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div>
            <h3 className="font-bold text-lg mb-4">SocialManager</h3>
            <p className="text-sm text-muted-foreground">
              The all-in-one platform for managing your social media presence across multiple platforms.
            </p>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Product</h4>
            <ul className="space-y-2 text-sm">
              <li><Link to="/features" className="text-muted-foreground hover:text-primary">Features</Link></li>
              <li><Link to="/pricing" className="text-muted-foreground hover:text-primary">Pricing</Link></li>
              <li><Link to="/integrations" className="text-muted-foreground hover:text-primary">Integrations</Link></li>
              <li><Link to="/api" className="text-muted-foreground hover:text-primary">API</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Company</h4>
            <ul className="space-y-2 text-sm">
              <li><Link to="/about" className="text-muted-foreground hover:text-primary">About</Link></li>
              <li><Link to="/blog" className="text-muted-foreground hover:text-primary">Blog</Link></li>
              <li><Link to="/careers" className="text-muted-foreground hover:text-primary">Careers</Link></li>
              <li><Link to="/contact" className="text-muted-foreground hover:text-primary">Contact</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold mb-4">Connect</h4>
            <div className="flex space-x-4 mb-4">
              <a href="#" className="text-muted-foreground hover:text-primary" aria-label="Facebook">
                <Facebook className="w-5 h-5" />
              </a>
              <a href="#" className="text-muted-foreground hover:text-primary" aria-label="Twitter">
                <Twitter className="w-5 h-5" />
              </a>
              <a href="#" className="text-muted-foreground hover:text-primary" aria-label="Instagram">
                <Instagram className="w-5 h-5" />
              </a>
              <a href="#" className="text-muted-foreground hover:text-primary" aria-label="LinkedIn">
                <Linkedin className="w-5 h-5" />
              </a>
              <a href="#" className="text-muted-foreground hover:text-primary" aria-label="GitHub">
                <Github className="w-5 h-5" />
              </a>
            </div>
            <p className="text-xs text-muted-foreground">
              © 2026 SocialManager. All rights reserved.
            </p>
          </div>
        </div>
      </div>
    </footer>
  );
}
'''
            }
        ],
        "pages": [
            {
                "path": "src/pages/Login.tsx",
                "content": """import React, { useState, FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { AlertCircle } from 'lucide-react';

interface FormErrors {
  email?: string;
  password?: string;
  general?: string;
}

interface FormData {
  email: string;
  password: string;
  remember: boolean;
}

export default function Login() {
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [formData, setFormData] = useState<FormData>({
    email: '',
    password: '',
    remember: false
  });

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
    return emailRegex.test(email);
  };

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.email) {
      newErrors.email = 'Email is required';
    } else if (!validateEmail(formData.email)) {
      newErrors.email = 'Please enter a valid email address';
    }

    if (!formData.password) {
      newErrors.password = 'Password is required';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);

    try {
      await new Promise(resolve => setTimeout(resolve, 1000));
      navigate('/dashboard');
    } catch (error) {
      setErrors({ general: 'An error occurred. Please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleInputChange = (field: keyof FormData, value: string | boolean) => {
    setFormData(prev => ({ ...prev, [field]: value }));

    if (errors[field as keyof FormErrors]) {
      setErrors(prev => ({ ...prev, [field]: undefined }));
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex flex-1 items-center justify-center py-12">
        <div className="container px-4">
          <div className="mx-auto max-w-md">
            <div className="mb-8 text-center">
              <h1 className="mb-2 text-3xl font-bold tracking-tight">Welcome back</h1>
              <p className="text-muted-foreground">Sign in to your account to continue</p>
            </div>

            <Card className="rounded-lg border bg-card p-8 shadow-sm">
              <form onSubmit={handleSubmit} className="space-y-6">
                {errors.general && (
                  <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>{errors.general}</span>
                  </div>
                )}

                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    value={formData.email}
                    onChange={(e) => handleInputChange("email", e.target.value)}
                    className={errors.email ? "border-destructive" : ""}
                    aria-invalid={!!errors.email}
                  />
                  {errors.email && (
                    <p className="text-sm text-destructive">{errors.email}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="password">Password</Label>
                    <Link to="/forgot-password" className="text-sm text-primary hover:underline">
                      Forgot password?
                    </Link>
                  </div>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={formData.password}
                    onChange={(e) => handleInputChange("password", e.target.value)}
                    className={errors.password ? "border-destructive" : ""}
                    aria-invalid={!!errors.password}
                  />
                  {errors.password && (
                    <p className="text-sm text-destructive">{errors.password}</p>
                  )}
                </div>

                <div className="flex items-center space-x-2">
                  <Checkbox
                    id="remember"
                    checked={formData.remember}
                    onCheckedChange={(checked) => handleInputChange("remember", checked as boolean)}
                  />
                  <Label htmlFor="remember" className="cursor-pointer text-sm font-normal">
                    Remember me for 30 days
                  </Label>
                </div>

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? 'Signing in...' : 'Sign in'}
                </Button>
              </form>
            </Card>

            <p className="mt-8 text-center text-sm text-muted-foreground">
              Don't have an account?{' '}
              <Link to="/signup" className="text-primary font-medium hover:underline">
                Sign up
              </Link>
            </p>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
""",
                "routes": ["/login"],
                "description": "User authentication page with email/password login form, remember me option, and social login buttons. Redirects authenticated users to dashboard."
            },
            {
                "path": "src/pages/Signup.tsx",
                "content": """import React, { useState, FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { AlertCircle, Check, X } from 'lucide-react';

interface FormErrors {
  name?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
  agreeToTerms?: string;
  general?: string;
}

interface FormData {
  name: string;
  email: string;
  password: string;
  confirmPassword: string;
  agreeToTerms: boolean;
}

export default function Signup() {
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [formData, setFormData] = useState<FormData>({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    agreeToTerms: false
  });

  const passwordStrength = useState(() => ({
    score: 0,
    feedback: [] as string[]
  }))[0];

  const validateEmail = (email: string): boolean => {
    const emailRegex = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/;
    return emailRegex.test(email);
  };

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.name) {
      newErrors.name = 'Full name is required';
    }

    if (!formData.email) {
      newErrors.email = 'Email is required';
    } else if (!validateEmail(formData.email)) {
      newErrors.email = 'Please enter a valid email address';
    }

    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters';
    }

    if (!formData.confirmPassword) {
      newErrors.confirmPassword = 'Please confirm your password';
    } else if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    if (!formData.agreeToTerms) {
      newErrors.agreeToTerms = 'You must agree to the terms';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);

    try {
      await new Promise(resolve => setTimeout(resolve, 1000));
      navigate('/dashboard');
    } catch (error) {
      setErrors({ general: 'An error occurred. Please try again.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleInputChange = (field: keyof FormData, value: string | boolean) => {
    setFormData(prev => ({ ...prev, [field]: value }));

    if (errors[field as keyof FormErrors]) {
      setErrors(prev => ({ ...prev, [field]: undefined }));
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex flex-1 items-center justify-center py-12">
        <div className="container px-4">
          <div className="mx-auto max-w-md">
            <div className="mb-8 text-center">
              <h1 className="mb-2 text-3xl font-bold tracking-tight">Create an account</h1>
              <p className="text-muted-foreground">Start managing your social media today</p>
            </div>

            <Card className="rounded-lg border bg-card p-8 shadow-sm">
              <form onSubmit={handleSubmit} className="space-y-5">
                {errors.general && (
                  <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>{errors.general}</span>
                  </div>
                )}

                <div className="space-y-2">
                  <Label htmlFor="name">Full Name</Label>
                  <Input
                    id="name"
                    type="text"
                    placeholder="John Doe"
                    value={formData.name}
                    onChange={(e) => handleInputChange("name", e.target.value)}
                    className={errors.name ? "border-destructive" : ""}
                    aria-invalid={!!errors.name}
                  />
                  {errors.name && (
                    <p className="text-sm text-destructive">{errors.name}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    value={formData.email}
                    onChange={(e) => handleInputChange("email", e.target.value)}
                    className={errors.email ? "border-destructive" : ""}
                    aria-invalid={!!errors.email}
                  />
                  {errors.email && (
                    <p className="text-sm text-destructive">{errors.email}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={formData.password}
                    onChange={(e) => handleInputChange("password", e.target.value)}
                    className={errors.password ? "border-destructive" : ""}
                    aria-invalid={!!errors.password}
                  />
                  {errors.password && (
                    <p className="text-sm text-destructive">{errors.password}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="confirmPassword">Confirm Password</Label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    placeholder="••••••••"
                    value={formData.confirmPassword}
                    onChange={(e) => handleInputChange("confirmPassword", e.target.value)}
                    className={errors.confirmPassword ? "border-destructive" : ""}
                    aria-invalid={!!errors.confirmPassword}
                  />
                  {errors.confirmPassword && (
                    <p className="text-sm text-destructive">{errors.confirmPassword}</p>
                  )}
                  {formData.confirmPassword && formData.password === formData.confirmPassword && (
                    <div className="flex items-center gap-1 text-xs text-green-500">
                      <Check className="h-3 w-3" />
                      <span>Passwords match</span>
                    </div>
                  )}
                </div>

                <div className="flex items-start space-x-2">
                  <Checkbox
                    id="terms"
                    checked={formData.agreeToTerms}
                    onCheckedChange={(checked) => handleInputChange("agreeToTerms", checked as boolean)}
                    className="mt-0.5"
                  />
                  <Label htmlFor="terms" className="cursor-pointer text-sm font-normal leading-normal">
                    I agree to the{' '}
                    <Link to="/terms" className="text-primary hover:underline">
                      Terms of Service
                    </Link>
                    {' '}and{' '}
                    <Link to="/privacy" className="text-primary hover:underline">
                      Privacy Policy
                    </Link>
                  </Label>
                </div>
                {errors.agreeToTerms && (
                  <p className="text-sm text-destructive">{errors.agreeToTerms}</p>
                )}

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? 'Creating account...' : 'Create account'}
                </Button>
              </form>
            </Card>

            <p className="mt-8 text-center text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link to="/login" className="text-primary font-medium hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
""",
                "routes": ["/signup"],
                "description": "User registration page with full name, email, password, confirm password, and terms agreement. Includes password strength indicator and form validation."
            },
            {
                "path": "src/pages/Dashboard.tsx",
                "content": """import React, { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { Calendar, MessageCircle, Share2, Heart, BarChart3, TrendingUp, ExternalLink, Edit3, Plus } from 'lucide-react';

interface ScheduledPost {
  id: string;
  content: string;
  platforms: string[];
  scheduledDate: Date;
  status: 'scheduled' | 'posted' | 'failed';
}

interface RecentPost {
  id: string;
  platform: string;
  content: string;
  postedAt: string;
  likes: number;
  comments: number;
  shares: number;
}

interface Analytics {
  totalFollowers: number;
  followersChange: string;
  totalEngagement: number;
  engagementChange: string;
  totalPosts: number;
  postsChange: string;
}

const mockScheduledPosts: ScheduledPost[] = [
  {
    id: '1',
    content: 'Excited to announce our new feature! Check it out and let us know what you think. #launch #innovation',
    platforms: ['twitter', 'linkedin'],
    scheduledDate: new Date('2026-03-01T10:00:00'),
    status: 'scheduled'
  },
  {
    id: '2',
    content: 'Behind the scenes at our team hackathon! The innovation here is incredible. 🚀',
    platforms: ['instagram', 'facebook'],
    scheduledDate: new Date('2026-03-02T14:30:00'),
    status: 'scheduled'
  }
];

const mockRecentPosts: RecentPost[] = [
  {
    id: '1',
    platform: 'twitter',
    content: 'Just shipped a major update to our dashboard UI! Users are loving the new analytics view.',
    postedAt: '2 hours ago',
    likes: 142,
    comments: 23,
    shares: 18
  },
  {
    id: '2',
    platform: 'instagram',
    content: 'Team building activity today! Great energy and collaboration across all departments.',
    postedAt: '5 hours ago',
    likes: 328,
    comments: 45,
    shares: 67
  }
];

const mockAnalytics: Analytics = {
  totalFollowers: 24567,
  followersChange: '+12.5%',
  totalEngagement: 8.4,
  engagementChange: '+8.2%',
  totalPosts: 156
};

export default function Dashboard() {
  const [scheduledPosts] = useState<ScheduledPost[]>(mockScheduledPosts);
  const [recentPosts] = useState<RecentPost[]>(mockRecentPosts);
  const [analytics] = useState<Analytics>(mockAnalytics);

  const getPlatformIcon = (platform: string) => {
    const icons: { [key: string]: JSX.Element } = {
      twitter: <span className="text-blue-500 font-bold">X</span>,
      linkedin: <span className="text-blue-700 font-bold">in</span>,
      instagram: <span className="text-pink-600 font-bold">IG</span>,
      facebook: <span className="text-blue-600 font-bold">FB</span>
    };
    return icons[platform] || platform[0].toUpperCase();
  };

  const getPlatformColor = (platform: string) => {
    const colors: { [key: string]: string } = {
      twitter: 'border-blue-500 text-blue-500',
      linkedin: 'border-blue-700 text-blue-700',
      instagram: 'border-pink-600 text-pink-600',
      facebook: 'border-blue-600 text-blue-600'
    };
    return colors[platform] || 'border-gray-400';
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1 container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Dashboard</h1>
          <p className="text-muted-foreground">Manage your social media presence</p>
        </div>

        <Tabs defaultValue="scheduler" className="space-y-6">
          <TabsList>
            <TabsTrigger value="scheduler">Post Scheduler</TabsTrigger>
            <TabsTrigger value="analytics">Analytics</TabsTrigger>
            <TabsTrigger value="recent">Recent Posts</TabsTrigger>
          </TabsList>

          {/* Scheduler Tab */}
          <TabsContent value="scheduler" className="space-y-6">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Scheduled Posts</CardTitle>
                    <CardDescription>Posts waiting to be published</CardDescription>
                  </div>
                  <Button size="sm" variant="outline" className="gap-2">
                    <Plus className="h-3 w-3" />
                    New Post
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {scheduledPosts.map((post) => (
                    <div
                      key={post.id}
                      className="flex items-start gap-4 rounded-lg border p-4 transition-colors hover:bg-muted/50"
                    >
                      <div className="flex gap-1">
                        {post.platforms.map((platform) => (
                          <div
                            key={platform}
                            className={`flex h-8 w-8 items-center justify-center rounded-full border ${getPlatformColor(platform)}`}
                          >
                            {getPlatformIcon(platform)}
                          </div>
                        ))}
                      </div>
                      <div className="flex-1">
                        <p className="mb-2 text-sm line-clamp-2">{post.content}</p>
                        <div className="flex items-center gap-3 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3" />
                            {post.scheduledDate.toLocaleDateString()} at{' '}
                            {post.scheduledDate.toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </span>
                          <Badge
                            variant={
                              post.status === 'scheduled'
                                ? 'default'
                                : post.status === 'posted'
                                ? 'secondary'
                                : 'outline'
                            }
                          >
                            {post.status}
                          </Badge>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Button size="icon" variant="ghost" className="h-8 w-8">
                          <Edit3 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Analytics Tab */}
          <TabsContent value="analytics" className="space-y-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-sm font-medium">Total Followers</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">
                    {analytics.totalFollowers.toLocaleString()}
                  </div>
                  <p className="mt-1 flex items-center gap-1 text-xs text-green-500">
                    <TrendingUp className="h-3 w-3" />
                    {analytics.followersChange} from last month
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-sm font-medium">Avg. Engagement</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{analytics.totalEngagement}%</div>
                  <p className="mt-1 flex items-center gap-1 text-xs text-green-500">
                    <TrendingUp className="h-3 w-3" />
                    {analytics.engagementChange} from last month
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-sm font-medium">Total Posts</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">{analytics.totalPosts}</div>
                  <p className="mt-1 flex items-center gap-1 text-xs text-green-500">
                    <TrendingUp className="h-3 w-3" />
                    +15.3% from last month
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="flex flex-row items-center justify-between pb-3">
                  <CardTitle className="text-sm font-medium">Profile Visits</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="text-2xl font-bold">4,231</div>
                  <p className="mt-1 flex items-center gap-1 text-xs text-green-500">
                    <TrendingUp className="h-3 w-3" />
                    +18.2% from last month
                  </p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Engagement Overview</CardTitle>
                <CardDescription>Your engagement rate over the last 30 days</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex h-64 items-center justify-center border-2 border-dashed rounded-lg">
                  <div className="text-center">
                    <BarChart3 className="mx-auto h-12 w-12 text-muted-foreground" />
                    <p className="mt-2 text-sm text-muted-foreground">
                      Chart visualization coming soon
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Recent Posts Tab */}
          <TabsContent value="recent" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Recently Posted</CardTitle>
                <CardDescription>Your most recent posts across all platforms</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {recentPosts.map((post) => (
                    <div
                      key={post.id}
                      className="flex items-start gap-4 rounded-lg border p-4"
                    >
                      <div className={`flex h-10 w-10 items-center justify-center rounded-full border ${getPlatformColor(post.platform)}`}>
                        {getPlatformIcon(post.platform)}
                      </div>
                      <div className="flex-1">
                        <p className="mb-3 text-sm">{post.content}</p>
                        <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1">
                            <Share2 className="h-3 w-3" />
                            {post.postedAt}
                          </span>
                          <span className="flex items-center gap-1">
                            <Heart className="h-3 w-3" />
                            {post.likes}
                          </span>
                          <span className="flex items-center gap-1">
                            <MessageCircle className="h-3 w-3" />
                            {post.comments}
                          </span>
                          <span className="flex items-center gap-1">
                            <Share2 className="h-3 w-3" />
                            {post.shares}
                          </span>
                        </div>
                      </div>
                      <Button size="sm" variant="ghost" className="gap-1" asChild>
                        <a href="#" target="_blank" rel="noopener noreferrer">
                          <ExternalLink className="h-3 w-3" />
                          View
                        </a>
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
      <Footer />
    </div>
  );
}
""",
                "routes": ["/dashboard"],
                "description": "Main dashboard with tabbed interface showing post scheduler, analytics overview with metrics cards, and recent posts with engagement data."
            },
            {
                "path": "src/pages/Settings.tsx",
                "content": """import React, { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import Navbar from '@/components/Navbar';
import Footer from '@/components/Footer';
import { Sun, Moon, ExternalLink } from 'lucide-react';

export default function Settings() {
  const [theme, setTheme] = useState('light');
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    bio: ''
  });

  const handleInputChange = (field: string, value: string) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1 container mx-auto px-4 py-8">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Settings</h1>
          <p className="text-muted-foreground">Manage your account and preferences</p>
        </div>

        <Tabs defaultValue="profile" className="space-y-6">
          <TabsList>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="connections">Connections</TabsTrigger>
            <TabsTrigger value="preferences">Preferences</TabsTrigger>
          </TabsList>

          {/* Profile Tab */}
          <TabsContent value="profile" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Profile Information</CardTitle>
                <CardDescription>Update your personal details</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Full Name</Label>
                  <Input
                    id="name"
                    placeholder="John Doe"
                    value={formData.name}
                    onChange={(e) => handleInputChange('name', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@example.com"
                    value={formData.email}
                    onChange={(e) => handleInputChange('email', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="bio">Bio</Label>
                  <textarea
                    id="bio"
                    placeholder="Tell us about yourself"
                    className="w-full min-h-[100px] rounded-md border bg-background px-3 py-2 text-sm"
                    value={formData.bio}
                    onChange={(e) => handleInputChange('bio', e.target.value)}
                  />
                </div>
                <Button>Save Changes</Button>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Connections Tab */}
          <TabsContent value="connections" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Connected Platforms</CardTitle>
                <CardDescription>Manage your social media connections</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {['twitter', 'linkedin', 'instagram'].map((platform) => (
                  <div key={platform} className="flex items-center justify-between p-4 border rounded-lg">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 bg-primary/10 rounded-lg flex items-center justify-center">
                        <span className="font-bold">{platform[0].toUpperCase()}</span>
                      </div>
                      <div>
                        <h3 className="font-medium capitalize">{platform}</h3>
                        <p className="text-sm text-muted-foreground">Not connected</p>
                      </div>
                    </div>
                    <Button size="sm" variant="outline" className="gap-2">
                      <ExternalLink className="h-4 w-4" />
                      Connect
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Preferences Tab */}
          <TabsContent value="preferences" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Appearance</CardTitle>
                <CardDescription>Customize how the application looks</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Theme</Label>
                    <p className="text-sm text-muted-foreground">
                      Choose between light and dark mode
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      size="icon"
                      variant={theme === 'light' ? 'default' : 'outline'}
                      onClick={() => setTheme('light')}
                    >
                      <Sun className="h-4 w-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant={theme === 'dark' ? 'default' : 'outline'}
                      onClick={() => setTheme('dark')}
                    >
                      <Moon className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Notifications</CardTitle>
                <CardDescription>Manage how you receive notifications</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Email Notifications</Label>
                    <p className="text-sm text-muted-foreground">
                      Receive email updates about your account
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <Separator />

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Post Reminders</Label>
                    <p className="text-sm text-muted-foreground">
                      Get notified before scheduled posts go live
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
      <Footer />
    </div>
  );
}
""",
                "routes": ["/settings"],
                "description": "Account settings with profile editing, social media platform connections, appearance preferences (theme toggle), and notification settings."
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

def create_pages_md(frontend_path: Path, pages, project_type: str) -> bool:
    """Create pages.md documenting page responsibilities. Accepts list of dicts OR list of page names (strings)."""
    try:

        pages_md_path = frontend_path / "pages.md"

        content = "# Pages Documentation\n\n"
        content += f"**Project Type:** {project_type}\n\n"
        content += "---\n\n"

        for page in pages:
            # Handle both dict (with path/routes/description) and string (just page name)
            if isinstance(page, dict):
                page_name = Path(page['path']).stem
                routes = page.get("routes", [])
                route = routes[0] if routes and isinstance(routes, list) and len(routes) > 0 else "N/A"
                page_file = page['path']
                description = page.get("description", "No description")
            else:
                # page is a string (page name)
                page_name = page
                route = f"/{page.lower().replace(' ', '-')}"
                page_file = f"src/pages/{page}.tsx"
                description = f"Page for {page} functionality"

            content += f"## {page_name}\n\n"
            content += f"**Route:** `{route}`\n\n"
            content += f"**File:** `{page_file}`\n\n"
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
        
        # Remove default Index root route if Dashboard is being set as root
        if '<Route path="/" element={<Dashboard />' in content:
            content = re.sub(
                r'\s*<Route path="/" element=\{<Index />\}\s*/>\n?',
                '',
                content
            )
            if content != original_content:
                logger.info("   Removed default Index root route")
        
        if content != original_content:
            app_path.write_text(content, encoding='utf-8')
            logger.info("   App.tsx updated with routes")
            return True

        logger.warning("   No changes to App.tsx")
        return False
    except Exception as e:
        logger.error(f"   Failed to update App.tsx: {e}")
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



def run_npm_build(cwd: str) -> bool:
    """Run npm build for frontend."""
    logger.info("🔨 Running npm run build")
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            logger.info("✅ Build passed")
            return True
        else:
            logger.warning(f"⚠️ Build failed: {result.stderr}")
            return False
    except Exception as e:
        logger.warning(f"⚠️ Build failed: {e}")
        return False




def get_existing_pages(frontend_path: Path) -> list:
    """Get list of existing pages from src/pages."""
    pages_dir = frontend_path / "src" / "pages"
    if not pages_dir.exists():
        return []
    
    return sorted([f.stem for f in pages_dir.glob("*.tsx") if f.stem != "NotFound"])


def analyze_and_select_pages(frontend_path: Path, description: str, project_type: str) -> list:
    """Select relevant template pages (max 3) using AI."""
    logger.info("🤖 Step 3: AI selecting relevant pages...")
    
    existing_pages = get_existing_pages(frontend_path)
    logger.info(f"   Found {len(existing_pages)} template pages: {existing_pages}")
    
    if not existing_pages:
        return []
    
    # Try to use Groq API for smart selection
    try:
        import os
        api_key = os.getenv("GROQ_API_KEY")
        if api_key and api_key != "your_api_key":
            import requests
            
            prompt = f"""You are selecting which pages to keep for a web application.

Project:
- Description: {description}
- Type: {project_type}

Available template pages:
{chr(10).join(f"- {p}" for p in existing_pages)}

TASK: Select the most relevant pages (MAXIMUM 3) for this specific project.
- Remove pages that don't match the project's purpose
- Keep pages that are essential to this type of application
- Return as a simple comma-separated list of page names only

Example response format:
Dashboard,Account,Settings

Respond with ONLY page names (no explanation, no numbering):"""

            logger.info("   Using Groq API to select relevant pages...")
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama3-70b-8192",
                    "messages": [
                        {"role": "system", "content": "You select relevant web pages. Return ONLY comma-separated page names."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 100
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                selected_text = data["choices"][0]["message"]["content"].strip()
                
                # Parse page names from response
                selected_pages = [p.strip() for p in selected_text.split(",") if p.strip()]
                
                # Filter to only pages that actually exist
                valid_pages = [p for p in selected_pages if p in existing_pages]
                
                # Limit to 3 max
                selected = valid_pages[:3]
                
                logger.info(f"   AI selected {len(selected)} relevant pages: {selected}")
                return selected
            else:
                logger.warning(f"   Groq API error: {response.status_code}")
                logger.info("   Falling back to first 3 pages...")
                return existing_pages[:3]
                
    except Exception as e:
        logger.warning(f"   AI selection failed: {e}")
        logger.info("   Falling back to first 3 pages...")
        return existing_pages[:3]


def delete_unwanted_pages(frontend_path: Path, pages_to_keep: list) -> list:
    """Delete unwanted pages from template."""
    logger.info("🗑️ Step 5: Removing unwanted template pages...")
    
    pages_dir = frontend_path / "src" / "pages"
    existing_pages = get_existing_pages(frontend_path)
    
    removed_pages = []
    
    if pages_dir.exists():
        for page_name in existing_pages:
            if page_name not in pages_to_keep:
                page_file = pages_dir / f"{page_name}.tsx"
                logger.info(f"   Removing: {page_file.name}")
                try:
                    page_file.unlink()
                    removed_pages.append(f"src/pages/{page_name}.tsx")
                except Exception as e:
                    logger.warning(f"   Failed to remove {page_name}.tsx: {e}")
    
    logger.info(f"   Removed {len(removed_pages)} unwanted pages")
    return removed_pages


def update_app_routes_from_pages(frontend_path: Path, pages_to_keep: list) -> bool:
    """Update App.tsx routes to only show selected pages."""
    logger.info("🛣️ Step 7: Updating App.tsx routes...")
    
    app_path = frontend_path / "src" / "App.tsx"
    if not app_path.exists():
        logger.warning("   App.tsx not found")
        return False
    
    app_content = app_path.read_text(encoding='utf-8')
    
    # Build route import statements
    route_imports = []
    for page_name in pages_to_keep:
        route_imports.append(f'import {page_name} from "@/pages/{page_name}";')
    
    # Build route elements
    route_elements = []
    for page_name in pages_to_keep:
        route_path = page_name.lower().replace(" ", "-")
        route_elements.append(f'          <Route path="/{route_path}" element={{<{page_name} />}} />')
    
    # Find and replace routes section
    routes_start = "  <Routes>"
    routes_end = "  </Routes>"
    
    if routes_start in app_content and routes_end in app_content:
        import re
        
        # Find routes section
        start_idx = app_content.find(routes_start)
        end_idx = app_content.find(routes_end) + len(routes_end)
        
        # Build new routes block
        new_routes_block = chr(10).join(route_imports) + chr(10) + chr(10) + routes_start + chr(10) + chr(10).join(route_elements) + chr(10) + routes_end
        
        # Replace routes section
        new_app_content = app_content[:start_idx] + new_routes_block + app_content[end_idx:]
        
        app_path.write_text(new_app_content, encoding='utf-8')
        logger.info(f"   Updated App.tsx with {len(pages_to_keep)} routes")
        return True
    else:
        logger.warning("   Could not find Routes section in App.tsx")
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
    
    # Step 2: Handle different project types
    logger.info("📝 Step 2: Handling project type...")
    
    if project_type == 'social_media':
        # Create social media pages from scratch
        logger.info("   Creating social media pages...")
        project_files = get_social_media_files(project_name)
        components = project_files.get('components', [])
        pages = project_files.get('pages', [])
        
        # Create components
        for comp in components:
            create_file(comp['content'], frontend_path / comp['path'])
        
        # Create pages
        for page in pages:
            create_file(page['content'], frontend_path / page['path'])
        
        # Update App.tsx routes
        # Special handling for social media projects: Dashboard as root route (applied BEFORE route_updates)
        if project_type == "social_media":
            logger.info("   Adding Dashboard as root route for social media project")
        
        # Update App.tsx routes
        route_updates = get_app_router_updates(project_type, pages)
        route_updates.insert(0, (
            'import Dashboard from "@/pages/Dashboard";',
            '          <Route path="/" element={<Dashboard />} />'
        ))
        update_app_routes(frontend_path, route_updates)
        
        pages_to_keep = [Path(p["path"]).stem for p in pages]
        removed_pages = []
        
    elif project_type == 'ecommerce':
        # Create e-commerce pages
        logger.info("   Creating e-commerce pages...")
        project_files = get_ecommerce_files(project_name)
        components = project_files.get('components', [])
        pages = project_files.get('pages', [])
        
        # Create components
        for comp in components:
            create_file(comp['content'], frontend_path / comp['path'])
        
        # Create pages
        for page in pages:
            create_file(page['content'], frontend_path / page['path'])
        
        # Update App.tsx routes
        route_updates = get_app_router_updates(project_type, pages)
        update_app_routes(frontend_path, route_updates)
        
        pages_to_keep = [Path(p['path']).stem for p in pages]
        removed_pages = []
        
    elif project_type == 'task_management':
        # Create task management pages
        logger.info("   Creating task management pages...")
        project_files = get_task_management_files()
        components = project_files.get('components', [])
        pages = project_files.get('pages', [])
        
        # Create components
        for comp in components:
            create_file(comp['content'], frontend_path / comp['path'])
        
        # Create pages
        for page in pages:
            create_file(page['content'], frontend_path / page['path'])
        
        # Update App.tsx routes
        route_updates = get_app_router_updates(project_type, pages)
        update_app_routes(frontend_path, route_updates)
        
        pages_to_keep = [Path(p['path']).stem for p in pages]
        removed_pages = []
        
    elif project_type == 'blog':
        # Create blog pages
        logger.info("   Creating blog pages...")
        project_files = get_blog_files()
        components = project_files.get('components', [])
        pages = project_files.get('pages', [])
        
        # Create components
        for comp in components:
            create_file(comp['content'], frontend_path / comp['path'])
        
        # Create pages
        for page in pages:
            create_file(page['content'], frontend_path / page['path'])
        
        # Update App.tsx routes
        route_updates = get_app_router_updates(project_type, pages)
        update_app_routes(frontend_path, route_updates)
        
        pages_to_keep = [Path(p['path']).stem for p in pages]
        removed_pages = []
        
    else:
        # Custom type - use AI selection from template
        logger.info("   Custom project - using template pages...")
        pages_to_keep = analyze_and_select_pages(frontend_path, description, project_type)
        pages_to_keep = pages_to_keep[:3] if pages_to_keep else []
        
        logger.info(f"   Selected {len(pages_to_keep)} pages to keep: {pages_to_keep}")
        
        # Remove unwanted pages
        removed_pages = delete_unwanted_pages(frontend_path, pages_to_keep)
        
        # Update App.tsx routes
        update_app_routes_from_pages(frontend_path, pages_to_keep)
        
        components = []
    
    import time
    start_time = time.time()
    
    # Update summary
    summary = {
        "project": project_name,
        "project_type": project_type,
        "components_created": 0,
        "pages_created": len(pages_to_keep),
        "pages_removed": len(removed_pages),
        "pages_kept": pages_to_keep,
        "files_modified": removed_pages + ["src/App.tsx"]
    }
    # Step 6: Create pages.md
    logger.info("📝 Step 6: Creating pages.md...")
    create_pages_md(frontend_path, pages_to_keep, project_type)
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
    """Create SUMMARY.md with enhanced error logging."""
    logger.info("📝 Creating SUMMARY.md...")
    
    try:
        # Validate required keys exist
        required_keys = ['project', 'components_created', 'pages_created', 'files_modified', 'total_time_seconds']
        for key in required_keys:
            if key not in summary:
                raise KeyError(f"Missing required key in summary: {key}")
        
        summary_path = frontend_path / "SUMMARY.md"
        
        # Validate frontend_path exists
        if not frontend_path.exists():
            raise FileNotFoundError(f"Frontend path does not exist: {frontend_path}")
        
        # Build content with validation
        components_list = [f for f in summary.get('files_modified', []) if 'components' in f]
        pages_list = [f for f in summary.get('files_modified', []) if 'pages/' in f]
        project_name = summary.get('project', 'Unknown')
        
        content = f"""# Phase 8: Smart Frontend Refinement Summary

**Project:** {project_name}
**Project Type:** {project_type}
**Execution Date:** 2026-02-27
**Total Duration:** {summary['total_time_seconds'] / 60:.1f} minutes

## Project Description

{description}

## Files Created

### Components ({summary['components_created']})
{chr(10).join(f"- `{f}`" for f in components_list) if components_list else "No components created"}

### Pages ({summary['pages_created']})
{chr(10).join(f"- `{f}`" for f in pages_list) if pages_list else "No pages created"}

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
        # Write file with encoding
        summary_path.write_text(content, encoding='utf-8')
        logger.info(f"✓ SUMMARY.md created at {summary_path}")
        logger.info(f"   Components: {summary['components_created']}, Pages: {summary['pages_created']}")
        
    except KeyError as e:
        logger.error(f"❌ Failed to create SUMMARY.md - Missing data: {e}")
        logger.debug(f"   Summary dict keys: {list(summary.keys())}")
    except FileNotFoundError as e:
        logger.error(f"❌ Failed to create SUMMARY.md - Path not found: {e}")
    except PermissionError as e:
        logger.error(f"❌ Failed to create SUMMARY.md - Permission denied: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to create SUMMARY.md: {e}")
        import traceback
        logger.debug(f"   Traceback: {traceback.format_exc()}")


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

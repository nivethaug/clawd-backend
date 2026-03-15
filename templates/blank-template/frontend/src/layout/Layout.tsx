import { Outlet } from "react-router-dom";

/**
 * Layout component - Main application layout wrapper
 * 
 * Provides the base structure for all pages using React Router nested routes.
 * Pages render inside the <Outlet /> component.
 * 
 * Structure:
 * - Full viewport height (h-screen)
 * - Flex container for future sidebar/header support
 * - Scrollable main content area
 */
const Layout = () => {
  return (
    <div className="flex h-screen w-full overflow-hidden">
      {/* Future: Sidebar component can go here */}
      {/* <Sidebar /> */}
      
      <div className="flex flex-col flex-1">
        {/* Future: Header component can go here */}
        {/* <Header /> */}
        
        {/* Main content area - scrollable */}
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default Layout;

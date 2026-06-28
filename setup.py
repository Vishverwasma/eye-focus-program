#!/usr/bin/env python3
"""
Eye Focus Monitor - Setup Script
Verifies environment and installs dependencies
"""

import subprocess
import sys
import os
from pathlib import Path


class SetupHelper:
    """Helper class for setup verification"""
    
    def __init__(self):
        self.python_version = sys.version_info
        self.venv_exists = self._check_venv()
        self.requirements_file = Path("requirements.txt")
    
    def _check_venv(self) -> bool:
        """Check if running in virtual environment"""
        return hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
    
    def verify_python_version(self) -> bool:
        """Verify Python 3.8+ is installed"""
        if self.python_version.major < 3 or (self.python_version.major == 3 and self.python_version.minor < 8):
            print("❌ Python 3.8+ required")
            print(f"   Current: Python {self.python_version.major}.{self.python_version.minor}")
            return False
        
        print(f"✅ Python {self.python_version.major}.{self.python_version.minor} detected")
        return True
    
    def verify_requirements_file(self) -> bool:
        """Verify requirements.txt exists"""
        if not self.requirements_file.exists():
            print("❌ requirements.txt not found")
            return False
        
        print(f"✅ requirements.txt found ({self.requirements_file.stat().st_size} bytes)")
        return True
    
    def check_virtual_environment(self) -> bool:
        """Check if running in virtual environment"""
        if not self.venv_exists:
            print("⚠️  Not running in virtual environment")
            print("   Recommendation: Create one with 'python -m venv venv'")
            response = input("   Continue anyway? (y/n): ").lower()
            return response == 'y'
        
        print("✅ Running in virtual environment")
        return True
    
    def install_dependencies(self) -> bool:
        """Install required dependencies"""
        print("\n📦 Installing dependencies...")
        
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "-r", "requirements.txt"
            ])
            print("✅ Dependencies installed successfully")
            return True
        
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install dependencies: {e}")
            return False
    
    def verify_imports(self) -> bool:
        """Verify all required packages are importable"""
        print("\n🔍 Verifying package imports...")
        
        required_packages = {
            'cv2': 'opencv-python',
            'mediapipe': 'mediapipe',
            'numpy': 'numpy',
            'psutil': 'psutil',
            'PIL': 'Pillow'
        }
        
        failed = []
        
        for module, package in required_packages.items():
            try:
                __import__(module)
                print(f"  ✅ {package}")
            except ImportError:
                print(f"  ❌ {package}")
                failed.append(package)
        
        if failed:
            print(f"\n❌ Missing: {', '.join(failed)}")
            return False
        
        print("✅ All packages verified")
        return True
    
    def check_camera_access(self) -> bool:
        """Verify camera is accessible"""
        print("\n📷 Checking camera access...")
        
        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    print("✅ Camera accessible")
                    return True
                else:
                    print("⚠️  Camera detected but failed to capture frame")
                    return False
            else:
                print("❌ Camera not detected or not accessible")
                print("   Ensure camera permissions are granted")
                return False
        
        except Exception as e:
            print(f"❌ Error checking camera: {e}")
            return False
    
    def run_verification_tests(self) -> bool:
        """Run test suite"""
        print("\n🧪 Running verification tests...")
        
        try:
            subprocess.check_call([
                sys.executable, "-m", "unittest", "test_verification", "-v"
            ])
            print("✅ All tests passed")
            return True
        
        except subprocess.CalledProcessError:
            print("⚠️  Some tests failed (may be due to missing camera)")
            return False
        
        except FileNotFoundError:
            print("⚠️  unittest or test_verification not found")
            return False
    
    def run_setup(self) -> bool:
        """Run complete setup process"""
        print("=" * 60)
        print("🎯 Eye Focus Monitor - Setup Wizard")
        print("=" * 60)
        
        checks = [
            ("Python Version", self.verify_python_version),
            ("Requirements File", self.verify_requirements_file),
            ("Virtual Environment", self.check_virtual_environment),
            ("Install Dependencies", self.install_dependencies),
            ("Verify Imports", self.verify_imports),
            ("Camera Access", self.check_camera_access),
        ]
        
        passed = 0
        failed = 0
        
        for check_name, check_func in checks:
            print(f"\n[{passed + failed + 1}/{len(checks)}] {check_name}...")
            
            try:
                if check_func():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"❌ Error: {e}")
                failed += 1
        
        print("\n" + "=" * 60)
        print(f"📊 Results: {passed} passed, {failed} failed")
        print("=" * 60)
        
        if failed == 0:
            print("\n✅ Setup completed successfully!")
            print("\n🚀 To start the application:")
            print("   python main.py")
            print("\n📋 Controls:")
            print("   Q - Quit")
            print("   S - Screenshot")
            print("   R - Reset statistics")
            return True
        else:
            print("\n❌ Setup incomplete. Please fix errors above.")
            return False


def main():
    """Main entry point"""
    try:
        setup = SetupHelper()
        success = setup.run_setup()
        sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user")
        sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

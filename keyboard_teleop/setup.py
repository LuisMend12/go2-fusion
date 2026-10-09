from setuptools import setup

package_name = 'keyboard_teleop'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name]
        ),
        (
            'share/' + package_name,
            ['package.xml']
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Your Name',
    maintainer_email='your_email@example.com',
    description='Keyboard teleoperation for the Unitree Go2',
    license='BSD-2-Clause',
    entry_points={
        'console_scripts': [
            'keyboard_teleop = keyboard_teleop.keyboard_teleop:main',
        ],
    },
)

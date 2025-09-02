import os

def print_tree(start_path, prefix=""):
    entries = os.listdir(start_path)
    entries.sort()
    for i, entry in enumerate(entries):
        path = os.path.join(start_path, entry)
        connector = "└── " if i == len(entries)-1 else "├── "
        print(prefix + connector + entry)
        if os.path.isdir(path):
            extension = "    " if i == len(entries)-1 else "│   "
            print_tree(path, prefix + extension)

print_tree("your_project_folder")

from rich.console import Console

console = Console()

# Create a table of servers
servers = [
    {"name": "server1", "status": "Up"},
    {"name": "server2", "status": "Down"},
    {"name": "server3", "status": "Up"}
]

table = console.table("Server Name", "Status")
for server in servers:
    table.add_row(server["name"], server["status"])

console.print(table)

# Create a progress bar
progress_bar = console.progress()

with progress_bar:
    for i in range(10):
        progress_bar.update(i + 1, total=10)
        time.sleep(1)  # Simulate some work

# Create coloured status text
console.log("Up", style="green")
console.log("Down", style="red")

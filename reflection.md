# Project Reflection

At first, I wanted to build SalonWait with Python's `argparse` as a command-line tool. I changed direction because customers and the salon owner needed a visual interface, so I built a full-stack website with Flask, HTML, CSS and JavaScript. Looking back, I initially underestimated how much the two user workflows mattered: customers need to find and book a slot, while the owner needs to manage walk-ins and appointments.

The full-stack version taught me that showing an available slot is not enough; the server must check it again when the customer books, since another booking could have taken it. I also learned to distinguish historical waiting-time estimates from live availability. Past records can inform an estimate, but cannot promise exactly when a customer will be served.

If I cut something, I would reduce the first version to the core journey: view services, book a slot, and let the owner manage the queue. I would postpone extra dashboard details until the salon had tried the basic workflow. I would also avoid treating example prices, opening hours and durations as confirmed facts; these need checking with the owner.

AI helped me get a working structure in place quickly, including the Flask routes, page templates and initial booking logic. It also helped surface cases to handle, such as overlapping bookings and invalid inputs. It wasted time when its first broad implementation did not match the project files and requirements closely enough, so I had to inspect and correct the result. I learned to treat generated code as a draft and verify that it fits the actual project.

The project is a prototype, not yet ready for real customer use. I would next confirm the salon's workflow and service details, gather more genuine timing data, and replace CSV storage with a database if the system were used by multiple people at once.

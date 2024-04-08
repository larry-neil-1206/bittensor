import inspect
import json
from jinja2 import Environment, FileSystemLoader
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Type
from pathlib import Path


def record_func(func: Callable) -> Callable:
    """
    Decorator function for recording the invocation of functions or methods,
    including input arguments, return values, and exceptions. The records
    are saved as JSON files, named to reflect the context of the call, and
    contain metadata about the caller and the function itself.

    Args:
        func (Callable): The function to decorate.

    Returns:
        Callable: The wrapped function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        # Preparing metadata
        caller_frame = inspect.stack()[1]
        caller_module = inspect.getmodule(caller_frame[0])
        caller_info = {
            "caller_file": caller_frame.filename,
            "caller_name": caller_frame.function,
            "caller_module": caller_module.__name__ if caller_module else None,
        }
        func_class = getattr(func, "__self__", None)
        class_name = func_class.__class__.__name__ if func_class else None

        # Execute the function, record output or exception
        try:
            result = func(*args, **kwargs)
            success = True
        except Exception as e:
            result = str(e)
            success = False

        record = {
            "metadata": caller_info,
            "class_name": class_name,
            "function_name": func.__name__,
            "arguments": {"args": args, "kwargs": kwargs},
            "success": success,
            "result": result,
        }

        # Naming and saving the record
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        func_identifier = f"{class_name + '.' if class_name else ''}{func.__name__}"
        filename = f"record_{func_identifier}_{timestamp}.json"
        file_path = Path(__file__).parent.joinpath("recordings").joinpath(filename)
        with open(file_path, "w") as f:
            json.dump(record, f, default=str, indent=4)

        if not success:
            raise

        return result

    return wrapper


def generate_pytest_file(
    test_file_path: Path,
    func: Callable,
    args: tuple,
    kwargs: dict,
    filename: str,
    success: bool,
):
    """
    Generates a pytest unit test file using Jinja2 templates.

    Args:
        test_file_path (Path): The path where the test file will be saved.
        func (Callable): The function that was recorded.
        args (tuple): The positional arguments used in the function call.
        kwargs (dict): The keyword arguments used in the function call.
        filename (str): The name of the file containing a previously recorded test.
        success (bool): Whether the function call was successful or raised an exception.
    """
    templates_dir = Path(__file__).parent.joinpath("templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("recorded_test.j2")

    arg_list = [repr(arg) for arg in args] + [
        f"{k}={repr(v)}" for k, v in kwargs.items()
    ]
    call_args = ", ".join(arg_list)
    invocation = f"{func.__name__}({call_args})"

    # Calculate relative module import path
    module = inspect.getmodule(func)
    module_path = (
        Path(module.__file__)
        .relative_to(Path(__file__).parent.parent)
        .as_posix()
        .rstrip(".py")
        .replace("/", ".")
    )
    test_content = template.render(
        module_path=module_path,
        func_name=func.__name__,
        invocation=invocation,
        recording_filename=filename,
        success=success,
        test_id=filename.split("_")[-1].split(".")[
            0
        ],  # Unique identifier from filename
    )

    with open(test_file_path, "w") as f:
        f.write(test_content)


def replay_test(recorded_func: Callable) -> Callable:
    """
    Decorator for replaying recorded inputs and outputs to test the consistency
    and correctness of a function using previously saved recordings.

    Args:
        recorded_func (Callable): The function to be tested using replayed data.

    Returns:
        Callable: A test wrapper that uses recorded data.
    """

    @wraps(recorded_func)
    def wrapper(*args, **kwargs) -> Any:
        # Determine the recording filename pattern
        func_class = getattr(recorded_func, "__self__", None)
        class_name = func_class.__class__.__name__ if func_class else None
        func_identifier = (
            f"{class_name + '.' if class_name else ''}{recorded_func.__name__}"
        )
        pattern = f"record_{func_identifier}_*.json"

        # Find all recording files matching the pattern
        recordings_path = Path(__file__).parent.joinpath("recordings")
        recording_files = list(recordings_path.glob(pattern))

        # If no recordings found, raise an exception
        if not recording_files:
            raise FileNotFoundError(f"No recordings found for {func_identifier}")

        # Loop through each recording, replay inputs, and compare outputs
        test_results = []
        for file_path in recording_files:
            with open(file_path, "r") as f:
                record = json.load(f)

            # Extract recorded arguments and results
            recorded_args = record["arguments"]["args"]
            recorded_kwargs = record["arguments"]["kwargs"]
            recorded_result = record["result"]
            success = record["success"]

            # Execute the function with recorded arguments
            try:
                result = recorded_func(*recorded_args, **recorded_kwargs)
                # Compare the result with the recorded result
                assert success and result == recorded_result
                test_results.append((file_path, True))
            except Exception as e:
                test_results.append((file_path, False, str(e)))

        # Return test results
        return test_results

    return wrapper

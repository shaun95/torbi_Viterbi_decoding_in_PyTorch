import functools
import math
import os
from typing import List, Optional, Union

import numpy as np
import torch
import torchutil

#TODO fix this name
from fastops import cppforward
from cudaops import forward as cuda_forward


###############################################################################
# Viterbi decoding
###############################################################################


def from_probabilities(
    observation: torch.Tensor,
    transition: Optional[torch.Tensor] = None,
    initial: Optional[torch.Tensor] = None,
    log_probs: bool = False,
    gpu: Optional[int] = None
) -> torch.Tensor:
    """Decode a time-varying categorical distribution

    Arguments
        observation
            Time-varying categorical distribution
            shape=(frames, states)
        transition
            Categorical transition matrix; defaults to uniform
            shape=(states, states)
        initial
            Categorical initial distribution; defaults to uniform
            shape=(states,)
        log_probs
            Whether inputs are in (natural) log space
        gpu
            GPU index to use for decoding. Defaults to CPU.

    Returns
        indices
            The decoded bin indices
            shape=(frames,)
    """
    frames, states = observation.shape
    device = 'cpu' if gpu is None else f'cuda:{gpu}
    if device == 'cpu':

        # Default to uniform initial probabilities
        if initial is None:
            initial = np.full(
                (frames,),
                math.log(1. / states),
                dtype=np.float32)

        # Ensure initial probabilities are in log space
        else:
            if not log_probs:
                initial = torch.log(initial)
            initial = initial.cpu().numpy().astype(np.float32)

        # Default to uniform transition probabilities
        if transition is None:
            transition = np.full(
                (frames, frames),
                math.log(1. / states),
                dtype=np.float32)

        # Ensure transition probabilities are in log space
        else:
            if not log_probs:
                transition = torch.log(transition)
            transition = transition.cpu().numpy().astype(np.float32)

        # Ensure observation probabilities are in log space
        if not log_probs:
            observation = torch.log(observation)
        observation = observation.cpu().numpy().astype(np.float32)

        # Initialize
        posterior = np.zeros_like(observation)
        memory = np.zeros(observation.shape, dtype=np.int32)
        probability = np.zeros((states, states), dtype=np.float32)

        # Forward pass
        with torchutil.time.context('forward'):
            cppforward(
                observation,
                transition,
                initial,
                posterior,
                memory,
                probability,
                frames,
                states)

        # Cast to torch
        posterior = torch.from_numpy(posterior)
        memory = torch.from_numpy(memory)

    else:

        # Default to uniform initial probabilities
        if initial is None:
            initial = torch.full(
                (frames,),
                math.log(1. / states),
                dtype=torch.float32,
                device=device)

        # Ensure initial probabilities are in log space
        else:
            if not log_probs:
                initial = torch.log(initial)
            initial = initial.to(device)

        # Default to uniform transition probabilities
        if transition is None:
            transition = torch.full(
                (frames, frames),
                math.log(1. / states),
                dtype=torch.float32,
                device=device)

        # Ensure transition probabilities are in log space
        else:
            if not log_probs:
                transition = torch.log(transition)
            transition = transition.to(device)

        # Ensure observation probabilities are in log space
        if not log_probs:
            observation = torch.log(observation)
        observation = observation.to(device)

        # Initialize
        posterior = torch.zeros_like(observation)
        memory = torch.zeros(
            observation.shape,
            dtype=torch.int32,
            device=device)
        probability = torch.zeros(
            (states, states),
            dtype=torch.float32,
            device=device)

        # Forward pass
        with torchutil.time.context('forward'):
            cuda_forward(
                observation,
                transition,
                initial,
                posterior,
                memory,
                probability,
                frames,
                states)

    with torchutil.time.context('backward'):

        # Backward pass
        indices = backward(posterior, memory)

    return indices


def from_file(
    input_file: Union[str, os.PathLike],
    transition_file: Optional[Union[str, os.PathLike]] = None,
    initial_file: Optional[Union[str, os.PathLike]] = None,
    log_probs: bool = False,
    gpu: Optional[int] = None
) -> torch.Tensor:
    """Decode a time-varying categorical distribution file

    Arguments
        input_file
            Time-varying categorical distribution file
            shape=(frames, states)
        transition_file
            Categorical transition matrix file; defaults to uniform
            shape=(states, states)
        initial_file
            Categorical initial distribution file; defaults to uniform
            shape=(states,)
        log_probs
            Whether inputs are in (natural) log space
        gpu
            GPU index to use for decoding. Defaults to CPU.

    Returns
        indices
            The decoded bin indices
            shape=(frames,)
    """
    observation = torch.load(input_file)
    if transition_file:
        transition = torch.load(transition_file)
    if initial_file:
        initial = torch.load(initial_file)
    return from_probabilities(observation, transition, initial, log_probs)


def from_file_to_file(
    input_file: Union[str, os.PathLike],
    output_file: Union[str, os.PathLike],
    transition_file: Optional[Union[str, os.PathLike]] = None,
    initial_file: Optional[Union[str, os.PathLike]] = None,
    log_probs: bool = False,
    gpu: Optional[int] = None
) -> None:
    """Decode a time-varying categorical distribution file and save

    Arguments
        input_file
            Time-varying categorical distribution file
            shape=(frames, states)
        output_file
            File to save decoded indices
        transition_file
            Categorical transition matrix file; defaults to uniform
            shape=(states, states)
        initial_file
            Categorical initial distribution file; defaults to uniform
            shape=(states,)
        log_probs
            Whether inputs are in (natural) log space
        gpu
            GPU index to use for decoding. Defaults to CPU.
    """
    indices = from_file(input_file, transition_file, initial_file, log_probs)
    torch.save(indices, output_file)


def from_files_to_files(
    input_files: List[Union[str, os.PathLike]],
    output_files: List[Union[str, os.PathLike]],
    transition_file: Optional[Union[str, os.PathLike]] = None,
    initial_file: Optional[Union[str, os.PathLike]] = None,
    log_probs: bool = False,
    gpu: Optional[int] = None
) -> None:
    """Decode time-varying categorical distribution files and save

    Arguments
        input_files
            Time-varying categorical distribution files
            shape=(frames, states)
        output_files
            Files to save decoded indices
        transition_file
            Categorical transition matrix file; defaults to uniform
            shape=(states, states)
        initial_file
            Categorical initial distribution file; defaults to uniform
            shape=(states,)
        log_probs
            Whether inputs are in (natural) log space
        gpu
            GPU index to use for decoding. Defaults to CPU.
    """
    decode_fn = functools.partial(
        from_file_to_file,
        transition_file=transition_file,
        initial_file=initial_file,
        log_probs=log_probs)
    for input_file, output_file in zip(input_files, output_files):
        decode_fn(input_file, output_file)


###############################################################################
# Utilities
###############################################################################


def backward(posterior, memory, size=None):
    """Get optimal pass from results of forward pass"""
    if size is None:
        size = len(posterior)

    # Initialize
    indices = torch.full(
        (size,),
        torch.argmax(posterior[-1]),
        dtype=torch.int32)

    # Backward
    for t in range(size - 2, -1, -1):
        indices[t] = memory[t + 1, indices[t + 1]]

    return indices

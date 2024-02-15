from typing import Union, Dict, Optional
import os
import contextlib
import multiprocessing as mp
import functools

import numpy as np
import torch
import torchutil

import torbi
from torbi.core import save, save_masked


###############################################################################
# Reference implementation of Viterbi decoding
###############################################################################

def from_dataloader(
    dataloader: torch.utils.data.DataLoader,
    output_files: Dict[
        Union[str, bytes, os.PathLike],
        Union[str, bytes, os.PathLike]],
    transition: Optional[torch.Tensor] = None,
    initial: Optional[torch.Tensor] = None,
    log_probs: bool = False,
    save_workers: int = 0,
) -> None:
    """Decode time-varying categorical distributions from dataloader

    Arguments
        dataloader
            A DataLoader object to do preprocessing for
            the DataLoader must yield batches (observation, batch_frames, input_filename)
        output_files
            A dictionary mapping input filenames to output filenames
        transition
            Categorical transition matrix; defaults to uniform
            shape=(states, states)
        initial
            Categorical initial distribution; defaults to uniform
            shape=(states,)
        log_probs
            Whether inputs are in (natural) log space
        save_workers
            The number of worker threads to use for async file saving

    Returns
        indices
            The decoded bin indices
            shape=(batch, frames)
    """
    # Setup multiprocessing
    if save_workers == 0:
        save_pool = contextlib.nullcontext()
    else:
        save_pool = mp.get_context('spawn').Pool(save_workers)

    with mp.get_context('spawn').Pool(os.cpu_count()//2) as librosa_pool:

        try:

            # Setup progress bar
            progress = torchutil.iterator(
                range(0, len(dataloader.dataset)),
                'reference',
                total=len(dataloader.dataset))

            from_probs = functools.partial(from_probabilities, transition=transition, initial=initial, log_probs=log_probs)

            # Iterate over dataset
            for observations, input_filenames in dataloader:

                # indices = []
                # for o in observations:
                #     indices.append(from_probs(o))
                with torchutil.time.context('librosa'):
                    indices = librosa_pool.map(from_probs, observations)

                # indices = from_probabilities(
                #     observation=observation,
                #     transition=transition,
                #     initial=initial,
                #     log_probs=log_probs,
                # )

                # Get output filenames
                filenames = [output_files[file] for file in input_filenames]

                # Save to disk
                if save_workers > 0:
                    raise NotImplementedError('set save_workers = 0')
                    # # Asynchronous save
                    # save_pool.starmap_async(
                    #     save_masked,
                    #     zip(result.cpu(), filenames, frame_lengths.cpu()))
                    # while save_pool._taskqueue.qsize() > 100:
                    #     time.sleep(1)

                else:

                    # Synchronous save
                    for indices, filename in zip(
                        indices,
                        filenames
                    ):
                        save(indices, filename)

                    # Increment by batch size
                progress.update(len(input_filenames))

        finally:

            # Close progress bar
            progress.close()

            # Maybe shutdown multiprocessing
            if save_workers > 0:
                save_pool.close()
                save_pool.join()
            librosa_pool.close()
            librosa_pool.join()

def from_probabilities(
    observation,
    transition=None,
    initial=None,
    log_probs=False
) -> torch.Tensor:
    """Perform reference Viterbi decoding"""
    import librosa
    device = observation.device
    frames, states = observation.shape

    # Setup initial probabilities
    if initial is None:
        initial = np.full(
            (states,),
            1. / states,
            dtype=np.float32)
    else:
        if log_probs:
            initial = torch.exp(initial)
        initial = initial.cpu().numpy().astype(np.float32)

    # Setup transition probabilities
    if transition is None:
        transition = np.full(
            (states, states),
            1. / states,
            dtype=np.float32)
    else:
        if log_probs:
            transition = torch.exp(transition)
        transition = transition.cpu().numpy().astype(np.float32)

    # Setup observation probabilities
    observation = observation.to(torch.float32).cpu()
    if log_probs:
        observation = torch.exp(observation)
    observation = observation.cpu().numpy().astype(np.float32)

    # Decode
    # with torchutil.time.context('librosa'):
    indices = librosa.sequence.viterbi(
        observation.T,
        transition,
        p_init=initial)

    # Cast to torch
    return torch.tensor(
        indices.astype(np.int32),
        dtype=torch.int,
        device=device)


def from_file(
    input_file,
    transition_file=None,
    initial_file=None,
    log_probs=False
) -> torch.Tensor:
    """Perform reference Viterbi decoding on a file"""
    observation = torch.load(input_file)
    if transition_file:
        transition = torch.load(transition_file) # comes as probs, not log probs
        if log_probs:
            transition = torch.log(transition)
    else:
        transition = None
    if initial_file:
        initial = torch.load(initial_file)
    else:
        initial = None
    return from_probabilities(observation, transition, initial, log_probs)


def from_file_to_file(
    input_file,
    output_file,
    transition_file=None,
    initial_file=None,
    log_probs=False
) -> None:
    """Perform reference Viterbi decoding on a file and save"""
    indices = from_file(input_file, transition_file, initial_file, log_probs)
    torch.save(indices, output_file)


def from_files_to_files(
    input_files,
    output_files,
    transition_file=None,
    initial_file=None,
    log_probs=False
) -> None:
    """Perform reference Viterbi decoding on many files and save"""
    # decode_fn = functools.partial(
    #     from_file_to_file,
    #     transition_file=transition_file,
    #     initial_file=initial_file,
    #     log_probs=log_probs)
    # for input_file, output_file in zip(input_files, output_files):
    #     decode_fn(input_file, output_file)
    mapping = {input_file: output_file for input_file, output_file in zip(input_files, output_files)}
    dataloader = torbi.data.loader(input_files, collate_fn=torbi.data.collate_reference)
    if transition_file:
        transition = torch.load(transition_file) # comes as probs, not log probs
        if log_probs:
            transition = torch.log(transition)
    else:
        transition = None
    if initial_file:
        initial = torch.load(initial_file)
    else:
        initial = None
    from_dataloader(
        dataloader=dataloader,
        output_files=mapping,
        transition=transition,
        initial=initial,
        log_probs=log_probs,
    )

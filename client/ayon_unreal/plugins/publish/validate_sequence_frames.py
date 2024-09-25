import clique
import os
from ayon_core.pipeline import (
    OptionalPyblishPluginMixin
)
import pyblish.api
from ayon_core.pipeline.publish import PublishValidationError


class ValidateSequenceFrames(pyblish.api.InstancePlugin,
                             OptionalPyblishPluginMixin):
    """Ensure the sequence of frames is complete

    The files found in the folder are checked against the frameStart and
    frameEnd of the instance. If the first or last file is not
    corresponding with the first or last frame it is flagged as invalid.
    """

    order = pyblish.api.ValidatorOrder
    label = "Validate Sequence Frames"
    families = ["render.local"]
    hosts = ["unreal"]
    optional = True

    def process(self, instance):
        if not self.is_active(instance.data):
            self.log.debug("Skipping Validate Frame Range...")
            return

        representations = instance.data.get("representations")

        folder_attributes = (
            instance.data
            .get("folderEntity", {})
            .get("attrib", {})
        )
        for repr in representations:
            repr_files = repr["files"]
            if isinstance(repr_files, str):
                continue

            ext = repr.get("ext")
            if not ext:
                _, ext = os.path.splitext(repr_files[0])
            elif not ext.startswith("."):
                ext = ".{}".format(ext)

            collections, remainder = clique.assemble(
                repr["files"], minimum_items=1,
                patterns=[clique.PATTERNS['frames']])

            if remainder:
                raise PublishValidationError(
                    "Some files have been found outside a sequence. "
                    f"Invalid files: {remainder}")
            if not collections:
                raise PublishValidationError(
                    "We have been unable to find a sequence in the "
                    "files. Please ensure the files are named "
                    "appropriately. "
                    f"Files: {repr_files}")
            if len(collections) > 1:
                raise PublishValidationError(
                    "Multiple collections detected. There should be a single "
                    "collection per representation. "
                    f"Collections identified: {collections}")

            collection = collections[0]
            frames = list(collection.indexes)

            if instance.data.get("slate"):
                # Slate is not part of the frame range
                frames = frames[1:]

            current_range = (frames[0], frames[-1])
            required_range = (folder_attributes.get("clipIn"),
                              folder_attributes.get("clipOut"))

            if current_range != required_range:
                raise PublishValidationError(
                    f"Invalid frame range: {current_range} - "
                    f"expected: {required_range}")

            missing = collection.holes().indexes
            if missing:
                raise PublishValidationError(
                    "Missing frames have been detected. "
                    f"Missing frames: {missing}")
